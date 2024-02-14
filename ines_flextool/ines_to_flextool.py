import spinedb_api as api
from spinedb_api import DatabaseMapping
import sys
sys.path.append("../src/")
import ines_transform
import yaml

url_db_in = sys.argv[1]
url_db_out = sys.argv[2]

with open('ines_to_flextool_entities.yaml', 'r') as file:
    entities_to_copy = yaml.load(file, yaml.BaseLoader)
with open('ines_to_flextool_parameters.yaml', 'r') as file:
    parameter_transforms = yaml.load(file, yaml.BaseLoader)
with open('ines_to_flextool_methods.yaml', 'r') as file:
    parameter_methods = yaml.load(file, yaml.BaseLoader)
with open('ines_to_flextool_entities_to_parameters.yaml', 'r') as file:
    entities_to_parameters = yaml.load(file, yaml.BaseLoader)


def main():
    with DatabaseMapping(url_db_in) as source_db:
        with DatabaseMapping(url_db_out) as target_db:
            ## Empty the database
            target_db.purge_items('parameter_value')
            target_db.purge_items('entity')
            target_db.purge_items('alternative')
            target_db.refresh_session()
            target_db.commit_session("Purged stuff")
            ## Copy alternatives
            for alternative in source_db.get_alternative_items():
                target_db.add_alternative_item(name=alternative.get('name'))
            target_db.commit_session("Added alternatives")

            c## Copy entites
            target_db = ines_transform.copy_entities(source_db, target_db, entities_to_copy)
            ## Copy numeric parameters(source_db, target_db, copy_entities)
            target_db = ines_transform.transform_parameters(source_db, target_db, parameter_transforms, ts_to_map=True)
            ## Copy method parameters
            target_db = ines_transform.process_methods(source_db, target_db, parameter_methods)
            ## Copy entities to parameters
            target_db = ines_transform.copy_entities_to_parameters(source_db, target_db, entities_to_parameters)
            ## Copy capacity specific parameters (manual scripting)
            target_db = process_capacities(source_db, target_db)
            ## Create a timeline from start_time and duration
            target_db = create_timeline(source_db, target_db)
            try:
                foo = target_db.commit_session("Added parameter values")
            except:
                print("commit parameters error")


def process_capacities(source_db, target_db):
    for unit_source in source_db.get_entity_items(entity_class_name="unit"):
        existing_units = {}
        u_to_n_capacity = {}
        u_to_n_investment_cost = {}
        u_to_n_fixed_cost = {}
        u_to_n_salvage_value = {}
        n_to_u_capacity = {}
        n_to_u_investment_cost = {}
        n_to_u_fixed_cost = {}
        n_to_u_salvage_value = {}

        # Store parameter existing_units (for the alternatives that define it)
        params = source_db.get_parameter_value_items(entity_class_name="unit", entity_name=unit_source["name"], parameter_definition_name="existing_units")
        for param in params:
            value = api.from_database(param["value"])
            if value:
                existing_units[param["alternative_name"]] = value
        # Store capacity related parameters in unit__to_node_source (for the alternatives that define it)
        for unit__to_node_source in source_db.get_entity_items(entity_class_name="unit__to_node"):
            if unit_source["name"] == unit__to_node_source["entity_byname"][0]:
                params = source_db.get_parameter_value_items(entity_class_name="unit__to_node", entity_name=unit__to_node_source["name"], parameter_definition_name="capacity")
                u_to_n_capacity.update(params_to_dict(params))
                params = source_db.get_parameter_value_items(entity_class_name="unit__to_node", entity_name=unit__to_node_source["name"], parameter_definition_name="investment_cost")
                u_to_n_investment_cost.update(params_to_dict(params))
                params = source_db.get_parameter_value_items(entity_class_name="unit__to_node", entity_name=unit__to_node_source["name"], parameter_definition_name="fixed_cost")
                u_to_n_fixed_cost.update(params_to_dict(params))
                params = source_db.get_parameter_value_items(entity_class_name="unit__to_node", entity_name=unit__to_node_source["name"], parameter_definition_name="salvage_value")
                u_to_n_salvage_value.update(params_to_dict(params))

        # If outputs don't have capacity defined, start plan B: Store parameter capacity in node__to_unit_source (for the alternatives that define it)
        if not u_to_n_capacity:
            for node__to_unit_source in source_db.get_entity_items(entity_class_name="node__to_unit"):
                if unit_source["name"] == node__to_unit_source["entity_byname"][1]:
                    params = source_db.get_parameter_value_items(entity_class_name="node__to_unit", entity_name=node__to_unit_source["name"], parameter_definition_name="capacity")
                    n_to_u_capacity.update(params_to_dict(params))

        # If outputs don't have investment_cost defined, start plan B: Store parameters investment_cost, fixed_cost and salvage_value in node__to_unit_source (for the alternatives that define it)
        if not u_to_n_investment_cost:
            for node__to_unit_source in source_db.get_entity_items(entity_class_name="node__to_unit"):
                if unit_source["name"] == node__to_unit_source["entity_byname"][1]:
                    params = source_db.get_parameter_value_items(entity_class_name="node__to_unit", entity_name=node__to_unit_source["name"], parameter_definition_name="investment_cost")
                    n_to_u_investment_cost.update(params_to_dict(params))
                    params = source_db.get_parameter_value_items(entity_class_name="node__to_unit", entity_name=node__to_unit_source["name"], parameter_definition_name="fixed_cost")
                    n_to_u_fixed_cost.update(params_to_dict(params))
                    params = source_db.get_parameter_value_items(entity_class_name="node__to_unit", entity_name=node__to_unit_source["name"], parameter_definition_name="salvage_value")
                    n_to_u_salvage_value.update(params_to_dict(params))

        # Write 'existing' capacity and virtual_unitsize to FlexTool DB (if capacity defined in unit outputs)
        if u_to_n_capacity:
            for u_to_n_alt, u_to_n_val in u_to_n_capacity.items():
                alt_ent_class = (u_to_n_alt, unit_source["entity_byname"], "unit")
                target_db = ines_transform.add_item_to_DB(target_db, "existing", alt_ent_class, u_to_n_val)
            if existing_units:
                for u_to_n_alt, u_to_n_val in u_to_n_capacity.items():
                    for existing_alt, existing_val in existing_units.items():
                        alt_ent_class = (u_to_n_alt, unit_source["entity_byname"], "unit")
                        virtual_unit_size = u_to_n_val / existing_val
                        target_db = ines_transform.add_item_to_DB(target_db, "virtual_unitsize", alt_ent_class, virtual_unit_size)
                        if u_to_n_alt is not existing_alt:
                            alt_ent_class = (existing_alt, unit_source["entity_byname"], "unit")
                            target_db = ines_transform.add_item_to_DB(target_db, "virtual_unitsize", alt_ent_class, virtual_unit_size)
        # Write 'existing' capacity and virtual_unitsize to FlexTool DB (if capacity is defined in unit inputs instead)
        elif n_to_u_capacity:
            for n_to_u_alt, n_to_u_val in n_to_u_capacity.items():
                alt_ent_class = (n_to_u_alt, unit_source["entity_byname"], "unit")
                target_db = ines_transform.add_item_to_DB(target_db, "existing", alt_ent_class, n_to_u_val)
            if existing_units:
                for n_to_u_alt, n_to_u_val in n_to_u_capacity.items():
                    for existing_alt, existing_val in existing_units.items():
                        alt_ent_class = (n_to_u_alt, unit_source["entity_byname"], "unit")
                        virtual_unit_size = n_to_u_val / existing_val
                        target_db = ines_transform.add_item_to_DB(target_db, "virtual_unitsize", alt_ent_class, virtual_unit_size)
                        if n_to_u_alt is not existing_alt:
                            alt_ent_class = (existing_alt, unit_source["entity_byname"], "unit")
                            target_db = ines_transform.add_item_to_DB(target_db, "virtual_unitsize", alt_ent_class, virtual_unit_size)

        # Write 'investment_cost', 'fixed_cost' and 'salvage_value' to FlexTool DB (if investment_cost defined in unit outputs)
        if u_to_n_investment_cost:
            for u_to_n_alt, u_to_n_val in u_to_n_investment_cost.items():
                alt_ent_class = (u_to_n_alt, unit_source["entity_byname"], "unit")
                target_db = ines_transform.add_item_to_DB(target_db, "invest_cost", alt_ent_class, u_to_n_val)
            for u_to_n_alt, u_to_n_val in u_to_n_fixed_cost.items():
                alt_ent_class = (u_to_n_alt, unit_source["entity_byname"], "unit")
                target_db = ines_transform.add_item_to_DB(target_db, "fixed_cost", alt_ent_class, u_to_n_val)
            for u_to_n_alt, u_to_n_val in u_to_n_salvage_value.items():
                alt_ent_class = (u_to_n_alt, unit_source["entity_byname"], "unit")
                target_db = ines_transform.add_item_to_DB(target_db, "salvage_value", alt_ent_class, u_to_n_val)
        # Write 'investment_cost', 'fixed_cost' and 'salvage_value' to FlexTool DB (if investment_cost is defined in unit inputs instead)
        elif n_to_u_investment_cost:
            for n_to_u_alt, n_to_u_val in n_to_u_investment_cost.items():
                alt_ent_class = (n_to_u_alt, unit_source["entity_byname"], "unit")
                target_db = ines_transform.add_item_to_DB(target_db, "invest_cost", alt_ent_class, n_to_u_val)
            for n_to_u_alt, n_to_u_val in n_to_u_fixed_cost.items():
                alt_ent_class = (n_to_u_alt, unit_source["entity_byname"], "unit")
                target_db = ines_transform.add_item_to_DB(target_db, "fixed_cost", alt_ent_class, n_to_u_val)
            for n_to_u_alt, n_to_u_val in n_to_u_salvage_value.items():
                alt_ent_class = (n_to_u_alt, unit_source["entity_byname"], "unit")
                target_db = ines_transform.add_item_to_DB(target_db, "salvage_value", alt_ent_class, n_to_u_val)

        # If no capacity nor investment_cost defined, warn.
        if not (u_to_n_capacity or u_to_n_investment_cost or n_to_u_capacity or n_to_u_investment_cost):
            print("Unit without capacity or investment_cost:" + unit_source["name"])

    return target_db


def create_timeline(source_db, target_db):
    for system_entity in source_db.get_entity_items(entity_class_name="system"):
        for param in source_db.get_parameter_value_items(entity_class_name="system", entity_name=system_entity["name"], parameter_definition_name="timeline"):
            value = api.from_database(param["value"], param["type"])
            if value.VALUE_TYPE == 'time series':
                # this works only if time resolution is <= 1 month - relativedelta does not have an easy way to calculate number of days over month boundaries
                value = api.Map([str(x) for x in value.indexes],
                                [float(x) for x in value.values + value.resolution[0].days*24 + value.resolution[0].hours + value.resolution[0].minutes/60],
                                index_name=value.index_name)
                value._value_type = "map"
            target_db = ines_transform.add_item_to_DB(target_db, "timestep_duration", [param["alternative_name"], (system_entity["name"], ), "timeline"], value)
    for solve_entity in source_db.get_entity_items(entity_class_name="solve_pattern"):
        for param_period in source_db.get_parameter_value_items(solve_entity["entity_class_name"], entity_name=solve_entity["name"], parameter_definition_name="period"):
            period = api.from_database(param_period["value"], param_period["type"])
            target_db = ines_transform.add_item_to_DB(target_db, "realized_periods",
                                         [param_period["alternative_name"], (solve_entity["name"],), "solve"], period,
                                         value_type="array")
            target_db = ines_transform.add_item_to_DB(target_db, "invest_periods",
                                         [param_period["alternative_name"], (solve_entity["name"],), "solve"], period,
                                         value_type="array")
            if param_period["type"] == "array":
                timeblock_set_array = []
                for period_array_member in period.values:
                    timeblock_set_array.append(solve_entity["name"])
                period__timeblock_set = api.Map(period.values, timeblock_set_array, index_name="period")
            else:
                period__timeblock_set = api.Map([period], [solve_entity["name"]], index_name="period")
            #print(period__timeblock_set)
            target_db = ines_transform.add_item_to_DB(target_db, "period_timeblockSet", [param_period["alternative_name"], (solve_entity["name"],), "solve"], period__timeblock_set, value_type="map")
        for param_start in source_db.get_parameter_value_items(solve_entity["entity_class_name"], entity_name=solve_entity["name"], parameter_definition_name="start_time"):
            value_start_time = api.from_database(param_start["value"], param_start["type"])
            for param_duration in source_db.get_parameter_value_items(solve_entity["entity_class_name"], entity_name=solve_entity["name"], parameter_definition_name="duration"):
                value_duration = api.from_database(param_duration["value"], param_duration["type"])
                block_duration = api.Map([str(value_start_time)], [value_duration.value.days * 24 + value_duration.value.hours + value_duration.value.minutes / 60], index_name="timestep")
                #print(block_duration)
                new_param, type_ = api.to_database(block_duration)
                added, error = target_db.add_parameter_value_item(entity_class_name="timeblockSet",
                                                                    entity_byname=(solve_entity["name"],),
                                                                    parameter_definition_name="block_duration",
                                                                    value=new_param,
                                                                    type=type_,
                                                                    alternative_name=param_start["alternative_name"]
                                                                    )
                if error:
                    print("writing block_duration failed: " + error)
                # To make sure all pairs of start and duration are captured:
                if param_start["alternative_name"] is not param_duration["alternative_name"]:
                    added, error = target_db.add_parameter_value_item(entity_class_name="timeblockSet",
                                                                        entity_byname=(solve_entity["name"],),
                                                                        parameter_definition_name="block_duration",
                                                                        value=new_param,
                                                                        type=type_,
                                                                        alternative_name=param_duration["alternative_name"]
                                                                        )
                    if error:
                        print("writing block_duration failed: " + error)
    for solve_entity in source_db.get_entity_items(entity_class_name="solve_pattern"):
        for system_entity in source_db.get_entity_items(entity_class_name="system"):
            added, error = target_db.add_item("entity",
                                                entity_class_name="timeblockSet__timeline",
                                                element_name_list=[solve_entity["name"], system_entity["name"]],
                                                )
            if error:
                print("creating entity for timeblockset__timeline failed: " + error)

    return target_db


def params_to_dict(params):
    dict_temp = {}
    for param in params:
        value = api.from_database(param["value"])
        if value:
            dict_temp[param["alternative_name"]] = value
    return dict_temp


if __name__ == "__main__":
    main()

