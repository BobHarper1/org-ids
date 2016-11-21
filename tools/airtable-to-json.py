# ToDo:
# - Add support for mappings
# - Add support for Need to Knows

import os
import requests
from ratelimit import rate_limited
import json
from collections import OrderedDict
import shutil


current_dir = os.path.dirname(os.path.realpath(__file__))

base = "appuUtoqGjQBojg9g"
api_key = os.environ['airtable_api_key']
table_cache = {}


def record_map(data):
    """Create a dictionary of records"""
    records = {}
    for record in data:
        records[record['id']] = record['fields']

    return records


@rate_limited(5)
def api_call(table, record=None, offset=""):
    """Fetch a table from the AirTable API"""
    if table in table_cache:
        return table_cache[table]
    else:
        r = requests.get("https://api.airtable.com/v0/" + base + "/" +
                         table + "?pageSize=100&view=Main%20View" +
                         "&offset=" + offset,
                         headers={"Authorization": "Bearer " + api_key})
        data = json.loads(r.text, object_pairs_hook=OrderedDict)
        records = record_map(data['records'])

        if 'offset' in data.keys():
            records = dict(list(records.items()) +
                           list(api_call(table=table,
                                         offset=data['offset']).items()))

        table_cache[table] = records
        return records


def build_item(item, mapping, table_mapping={}):
    output_item = OrderedDict()
    for field in mapping.keys():
        if field in item.keys():
            # If there is a table mapping for the field we want to resolve
            # the cross-reference
            if field in table_mapping.keys():
                # We assume we have one-to-many arrays. This may not always
                # be true of all tables.
                output_item[mapping[field]] = []
                for record in item[field]:
                    output_item[mapping[field]].append(build_item(
                        table_mapping[field]['data'][record],
                        table_mapping[field]['mapping']))
            else:
                output_item[mapping[field]] = item[field]
        else:
            output_item[mapping[field]] = None
    return output_item


def build_output(dataset, mapping, table_mapping={}):
    """Take a mapping between fields in Airtable and fields for output and create a dictionary"""
    output = []
    for k, source_item in dataset.items():
        output.append(build_item(source_item, mapping, table_mapping))
    return output

jurisdictions = api_call("Jurisdictions")
subnational = api_call("Sub-national%20jurisdictions")
sectors = api_call("Sectors")
types = api_call("Organisation%20Types")
lists = api_call("Organisation%20lists")
n2k = api_call("Need%20to%20know")



# Create mappings between AirTable fields and the output we want.
# A map just renames keys
# A table map indicates how record identifiers should be resolved,
# and what data from the related table should be included

country_map = {"Code": "countryCode", "Country": "country"}

subnational_map = {"Code": "regionCode",
                   "Jurisdiction": "country", "Title": "regionName"}
subnational_table_map = {"Jurisdiction":
                         {"data": jurisdictions,
                          "mapping": country_map}}

sector_map = {"Name": "name"}

orgtype_map = {"Organisation Type": "name", "Parent": "subtypeOf"}
orgtype_table_map = {"Parent": {"data": types,
                                "mapping": {"Organisation Type": "name"}}}

identifier_map = OrderedDict({"code": "code",
                              "name": "name",
                              "description": "description",
                              "Jurisdiction": "jurisdiction",
                              "url": "url",
                              "public-database": "publicDatabase",
                              "Legal Structure": "structure",
                              "Example identifier(s)": "exampleIdentifiers",
                              "Register Type": "registerType",
                              "Available online?": "availableOnline",
                              "Finding the identifiers": "guidanceOnLocatingIds",
                              "Openly licensed": "licenseStatus",
                              "License details": "licenseDetails",
                              "Online availability details": "onlineAccessDetails",
                              "Access to data": "dataAccessProperties",
                              "Data access details": "dataAccessDetails",
                              "Data features": "datasetFeatures",
                              "In OpenCorporates?": "opencorporates",
                              "Languages supported": "languages",
                              "Sector": "sector",
                              "Sub-national": "subnational",
                              "Wikipedia page": "wikipedia",
                              "Confirmed?": "confirmed",
                              "Last Updated": "lastUpdated",
                              "Deprecated": "deprecated",
                              "AKA": "former_prefixes",
                              "Source": "source"})

identifier_table_map = {"Jurisdiction": {"data": jurisdictions,
                                         "mapping": country_map},
                        "Legal Structure": {"data": types,
                                            "mapping": orgtype_map},
                        "Sector": {"data": sectors,
                                   "mapping": sector_map},
                        "Sub-national": {"data": subnational,
                                         "mapping": subnational_map}}


n2k_map = {"Title": "title",
           "Jurisdiction": "jurisdiction",
           "Legal Structure": "structure",
           "Identifier List": "prefix",
           "Sector": "sector",
           "Description": "text"}

n2k_table_map = {"Jurisdiction": {"data": jurisdictions,
                                  "mapping": country_map},
                 "Legal Structure": {"data": types,
                                     "mapping": orgtype_map},
                 "Sector": {"data": sectors,
                            "mapping": sector_map},
                 "Identifier List": {
    "data": lists,
    "mapping": {"code": "code", "name": "name"}
}}

# Write out the data
with open("../data/jurisdictions.json", "w") as outfile:
    json.dump(build_output(jurisdictions, country_map), outfile, indent=4)

with open("../data/subnational.json", "w") as outfile:
    json.dump(build_output(subnational, mapping=subnational_map,
                           table_mapping=subnational_table_map),
              outfile, indent=4)

with open("../data/sectors.json", "w") as outfile:
    json.dump(build_output(sectors, sector_map), outfile, indent=4)


with open("../data/organisation_types.json", "w") as outfile:
    json.dump(build_output(types, orgtype_map,
                           orgtype_table_map), outfile, indent=4)


with open("../data/prefix_list.json", "w") as outfile:
    json.dump(build_output(lists, identifier_map,
                           identifier_table_map), outfile, indent=4)

with open("../data/need_to_know.json", "w") as outfile:
    json.dump(build_output(n2k, n2k_map,
                           n2k_table_map), outfile, indent=4)



data_dir = os.path.join(current_dir, '../codes')
output = build_output(lists, identifier_map, identifier_table_map)

try:
    shutil.rmtree(data_dir)
except FileNotFoundError:
    pass


for item in output:
    code = item['code']
    code_dir = os.path.join(data_dir, code.split('-')[0].lower())
    try:
        os.makedirs(code_dir)
    except FileExistsError:
        pass
    os.path.join(code_dir, code)

    sorted_item = OrderedDict()
    for key, value in sorted(item.items()):
        if not value:
            continue
        sorted_item[key] = value

    with open(os.path.join(code_dir, code).lower() + '.json', 'w+') as code_file:
        json.dump(sorted_item, code_file, indent=2)




