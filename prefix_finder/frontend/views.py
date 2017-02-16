import os
import json
import glob
import zipfile
import io
import warnings

from django.shortcuts import render
from django.http import HttpResponse
from django.conf import settings
import requests


current_dir = os.path.dirname(os.path.realpath(__file__))

##globals
lookups = None
org_id_lists = None
git_commit_ref = ''


def load_schemas_from_github():
    schemas = {}
    response = requests.get("https://github.com/OpenDataServices/org-ids/archive/new-schema-frontend.zip")
    with zipfile.ZipFile(io.BytesIO(response.content)) as ziped_repo:
        for filename in ziped_repo.namelist():
            filename_split = filename.split("/")[1:]
            if len(filename_split) == 2 and filename_split[0] == "schema" and filename_split[-1].endswith(".json"):
                with ziped_repo.open(filename) as schema_file:
                    schemas[filename_split[-1].split(".")[0]] = json.loads(schema_file.read().decode('utf-8'))
    return schemas

def load_schemas_from_disk():
    schemas = {}
    schema_dir = os.path.join(current_dir, '../../schema')
    for file_path in glob.glob(schema_dir + '/*.json'):
        with open(file_path) as data:
            schemas[file_path.split('/')[-1].split(".")[0]] = json.load(data)

    return schemas



def create_codelist_lookups(schemas):

    lookups = {}

    lookups['coverage'] = [(item['code'], item['title']['en']) for item in schemas['codelist-coverage']['coverage']] 
    lookups['subnationalCoverage'] = [(item['code'], item['title']['en']) for item in schemas['codelist-coverage']['subnationalCoverage']] 

    lookups['structure'] = [(item['code'], item['title']['en']) for item in schemas['codelist-structure']['structure'] if not item['parent']] 
    lookups['substructure'] = [(item['code'], item['title']['en']) for item in schemas['codelist-structure']['structure'] if item['parent']] 

    lookups['sector'] = [(item['code'], item['title']['en']) for item in schemas['codelist-sector']['sector']] 

    return lookups



def load_org_id_lists_from_github():
    org_id_lists = []
    response = requests.get("https://github.com/OpenDataServices/org-ids/archive/new-schema-frontend.zip")
    with zipfile.ZipFile(io.BytesIO(response.content)) as ziped_repo:
        for filename in ziped_repo.namelist():
            filename_split = filename.split("/")[1:]
            if len(filename_split) == 3 and filename_split[0] == "codes" and filename_split[-1].endswith(".json"):
                with ziped_repo.open(filename) as schema_file:
                    org_id_lists.append(json.loads(schema_file.read().decode('utf-8')))
    return org_id_lists


def load_org_id_lists_from_disk():
    codes_dir = os.path.join(current_dir, '../../codes')
    org_id_lists = []
    for org_id_list_file in glob.glob(codes_dir + '/*/*.json'):
        with open(org_id_list_file) as org_id_list:
            org_id_lists.append(json.load(org_id_list))

    return org_id_lists


def refresh_data():
    global lookups 
    global org_id_lists 
    global git_commit_ref

    try:
        sha = requests.get(
            'https://api.github.com/repos/opendataservices/org-ids/branches/new-schema-frontend'
        ).json()['commit']['sha']
        using_github = True
        if sha == git_commit_ref:
            return "Not updating as sha has not changed: {}".format(sha)
    except Exception:
        using_github = False

    if settings.LOCAL_DATA:
        using_github = False

    if using_github:
        try:
            schemas  = load_schemas_from_github()
        except Exception as e:
            raise
            using_github = False
            schemas = load_schemas_from_disk()
    else:
        schemas = load_schemas_from_disk()

    lookups = create_codelist_lookups(schemas)
    
    if using_github:
        try:
            org_id_lists = load_org_id_lists_from_github()
        except:
            raise
            using_github = False
            org_id_lists = load_org_id_lists_from_disk()
    else:
        org_id_lists = load_org_id_lists_from_disk()

    if using_github:
        git_commit_ref = sha
        return "Loaded from github: {}".format(sha)
    else:
        return "Loaded from disk"



refresh_data()

def filter_and_score_results(query):
    indexed = {org_id_list['code']: org_id_list.copy() for org_id_list in org_id_lists}
    for prefix in list(indexed.values()):
        prefix['quality'] = 1
        prefix['relevance'] = 0
        list_type = prefix.get('listType')
        if list_type and list_type == 'primary':
            prefix['quality'] = 2

    coverage = query.get('coverage')
    structure = query.get('structure')
    sector = query.get('sector')

    for prefix in list(indexed.values()):
        if coverage:
            if prefix['coverage']:
                if coverage in prefix['coverage']:
                    prefix['relevance'] = prefix['relevance'] + 10
                    if len(prefix['coverage']) == 1:
                        prefix['relevance'] = prefix['relevance'] + 1
                else:
                    indexed.pop(prefix['code'], None)
        else:
            if not prefix['coverage']:
                prefix['relevance'] = prefix['relevance'] + 2


        if structure:
            if prefix['structure']:
                if structure in prefix['structure']:
                    prefix['relevance'] = prefix['relevance'] + 10
                    if len(prefix['structure']) == 1:
                        prefix['relevance'] = prefix['relevance'] + 1
                else:
                    indexed.pop(prefix['code'], None)
        else:
            if not prefix['structure']:
                prefix['relevance'] = prefix['relevance'] + 2
            
        if sector:
            if prefix['sector']:
                if sector in prefix['sector']:
                    prefix['relevance'] = prefix['relevance'] + 10
                    if len(prefix['sector']) == 1:
                        prefix['relevance'] = prefix['relevance'] + 1
                else:
                    indexed.pop(prefix['code'], None)
        else:
            if not prefix['sector']:
                prefix['relevance'] = prefix['relevance'] + 2


    all_results = {"suggested": [],
                   "recommended": [],
                   "other": []}

    if not indexed:
        return all_results

    top_relevence = max(prefix['relevance'] for prefix in indexed.values())
                   
    for num, value in enumerate(sorted(indexed.values(), key=lambda k: -(k['relevance'] * 100 + k['quality']))):
        if num == 0:
            all_results['suggested'].append(value)
        elif value['relevance'] > 4:
            all_results['recommended'].append(value)
        else:
            all_results['other'].append(value)

    return all_results


def update_lists(request):
    return HttpResponse(refresh_data())


def home(request):
    query = {key: value[0] for key, value in dict(request.GET).items()
             if key in ['coverage', 'structure', 'sector']}
    context = {
        "org_id_lists": org_id_lists,
        "lookups": lookups,
        "query": query
    }
    if query:
        context['all_results'] = filter_and_score_results(query)
         
    return render(request, "home.html", context=context)


def list_details(request, prefix):
    prefix_low = prefix.lower()
    prefix_dir = prefix_low.split('-')[0]
    filepath = '{}/{}.json'.format(prefix_dir, prefix_low)
    codes_dir = os.path.join(current_dir, '../../codes')

    with open(os.path.join(codes_dir, filepath)) as data:
        org_list = json.load(data)

    return render(request, 'list.html', context={'org_list': org_list})
