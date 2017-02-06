# This script updates the schema with new enumerations from the jurisdictions list
import json
import jsonmerge 
import collections

def update_schema(schema,filename,codelist,target,array=True):

    enum = []
    enum_titles = []

    with open(filename) as file:
        filedata = json.loads(file.read(),object_pairs_hook=collections.OrderedDict)
        for code in filedata[codelist]:
            enum.append(code['code'])
            enum_titles.append(code['title']['en'])

    if "/" in target:
        if array:
            schema['properties'][target.split("/")[0]]['properties'][target.split("/")[1]]['items']['enum'] = enum
            schema['properties'][target.split("/")[0]]['properties'][target.split("/")[1]]['items']['options']['enum_titles'] = enum_titles
        else:
            schema['properties'][target.split("/")[0]]['properties'][target.split("/")[1]]['enum'] = enum
            schema['properties'][target.split("/")[0]]['properties'][target.split("/")[1]]['options']['enum_titles'] = enum_titles
    else:
        if array:
            schema['properties'][target]['items']['enum'] = enum
            schema['properties'][target]['items']['options']['enum_titles'] = enum_titles
        else:
            schema['properties'][target]['enum'] = enum
            schema['properties'][target]['options']['enum_titles'] = enum_titles
    
    return schema


with open("list-schema.json") as schema_file:
    schema = json.loads(schema_file.read(),object_pairs_hook=collections.OrderedDict)


schema = update_schema(schema,"codelist-jurisdictions.json","national","jurisdiction")
schema = update_schema(schema,"codelist-jurisdictions.json","subnational","subnationalJurisdiction")
schema = update_schema(schema,"codelist-structure.json","structure","structure")
schema = update_schema(schema,"codelist-sector.json","sector","sector")
schema = update_schema(schema,"codelist-listType.json","listType","listType",False) 
schema = update_schema(schema,"codelist-availability.json","availability","data/availability")  ## NEED TO UPDATE SCRIPT TO COPE WITH THIS
schema = update_schema(schema,"codelist-features.json","features","data/features")  ## NEED TO UPDATE SCRIPT TO COPE WITH THIS
schema = update_schema(schema,"codelist-licenseStatus.json","licenseStatus","data/licenseStatus",False)

# schema = jsonmerge.merge(schema,jurisdiction)
# schema = jsonmerge.merge(schema,subnational)
# schema = jsonmerge.merge(schema,structure)
# schema = jsonmerge.merge(schema,sector)
# schema = jsonmerge.merge(schema,listType)

print(json.dumps(schema,indent=4))

