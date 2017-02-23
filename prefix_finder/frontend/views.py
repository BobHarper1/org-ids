import os
import json
import glob
import zipfile
import io

from django.shortcuts import render
from django.http import HttpResponse, Http404
from django.conf import settings
import requests

RELEVANCE = {
    "MATCH_DROPDOWN": 10,
    "MATCH_DROPDOWN_ONLY_VALUE": 1,
    "MATCH_EMPTY": 2,
    "RECOMENDED_THRESHOLD": 5
}

current_dir = os.path.dirname(os.path.realpath(__file__))

##globals
lookups = None
org_id_dict = None
git_commit_ref = ''


def load_schemas_from_github():
    schemas = {}
    response = requests.get("https://github.com/OpenDataServices/org-ids/archive/master.zip")
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
    lookups['coverage'] = sorted(
        [(item['code'], item['title']['en']) for item in schemas['codelist-coverage']['coverage']],
        key=lambda tup: tup[1]
    )
    lookups['structure'] = [(item['code'], item['title']['en']) for item in schemas['codelist-structure']['structure'] if not item['parent']]
    lookups['sector'] = [(item['code'], item['title']['en']) for item in schemas['codelist-sector']['sector']]

    lookups['subnational'] = {}
    for item in schemas['codelist-coverage']['subnationalCoverage']:
        if lookups['subnational'].get(item['countryCode']):
            lookups['subnational'][item['countryCode']].append((item['code'], item['title']['en']))
        else:
            lookups['subnational'][item['countryCode']] = [(item['code'], item['title']['en'])]

    lookups['substructure'] = {}
    for item in schemas['codelist-structure']['structure']:
        if item['parent']:
            code_title = (item['code'], item['title']['en'].split(' > ')[1])
            if lookups['substructure'].get(item['parent']):
                lookups['substructure'][item['parent']].append(code_title)
            else:
                lookups['substructure'][item['parent']] = [code_title]

    return lookups


def load_org_id_lists_from_github():
    org_id_lists = []
    response = requests.get("https://github.com/OpenDataServices/org-ids/archive/master.zip")
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


def add_coverage_titles(org_lists):
    '''Add coverage_titles and subnationalCoverage_titles to organisation lists'''
    for org_list in org_lists:
        coverage_codes = org_list.get('coverage')
        if coverage_codes:
            org_list['coverage_titles'] = [tup[1] for tup in lookups['coverage'] if tup[0] in coverage_codes]
        subnational_codes = org_list.get('subnationalCoverage')
        if subnational_codes:
            subnational_coverage = []
            for country in coverage_codes:
                subnational_coverage.extend(lookups['subnational'][country])
            org_list['subnationalCoverage_titles'] = [tup[1] for tup in subnational_coverage if tup[0] in subnational_codes]


def refresh_data():
    global lookups
    global org_id_dict
    global git_commit_ref

    try:
        sha = requests.get(
            'https://api.github.com/repos/opendataservices/org-ids/branches/master'
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
            schemas = load_schemas_from_github()
        except Exception:
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

    add_coverage_titles(org_id_lists)
    org_id_dict = {org_id_list['code']: org_id_list for org_id_list in org_id_lists if org_id_list['confirmed']}

    if using_github:
        git_commit_ref = sha
        return "Loaded from github: {}".format(sha)
    else:
        return "Loaded from disk"


refresh_data()


def filter_and_score_results(query):
    indexed = {key: value.copy() for key, value in org_id_dict.items()}
    for prefix in list(indexed.values()):
        prefix['quality'] = 1
        prefix['relevance'] = 0
        list_type = prefix.get('listType')
        if list_type and list_type == 'primary':
            prefix['quality'] = 2

    coverage = query.get('coverage')
    subnational = query.get('subnational')
    structure = query.get('structure')
    substructure = query.get('substructure')
    sector = query.get('sector')

    for prefix in list(indexed.values()):
        if coverage:
            if prefix['coverage']:
                if coverage in prefix['coverage']:
                    prefix['relevance'] += RELEVANCE["MATCH_DROPDOWN"]
                    if len(prefix['coverage']) == 1:
                        prefix['relevance'] += RELEVANCE["MATCH_DROPDOWN_ONLY_VALUE"]
                else:
                    indexed.pop(prefix['code'], None)
        else:
            if not prefix['coverage']:
                prefix['relevance'] += RELEVANCE["MATCH_EMPTY"]

        if subnational:
            if prefix['subnationalCoverage'] and subnational in prefix['subnationalCoverage']:
                prefix['relevance'] += RELEVANCE["MATCH_DROPDOWN"] * 2
                if len(prefix['subnationalCoverage']) == 1:
                    prefix['relevance'] += RELEVANCE["MATCH_DROPDOWN_ONLY_VALUE"]
            else:
                indexed.pop(prefix['code'], None)

        if structure:
            if prefix['structure']:
                if structure in prefix['structure']:
                    prefix['relevance'] += RELEVANCE["MATCH_DROPDOWN"]
                    if len(prefix['structure']) == 1:
                        prefix['relevance'] += RELEVANCE["MATCH_DROPDOWN_ONLY_VALUE"]
                else:
                    indexed.pop(prefix['code'], None)
        else:
            if not prefix['structure']:
                prefix['relevance'] += RELEVANCE["MATCH_EMPTY"]

        if substructure:
            if prefix['structure'] and substructure in prefix['structure']:
                    prefix['relevance'] += RELEVANCE["MATCH_DROPDOWN"] * 2
            else:
                indexed.pop(prefix['code'], None)

        if sector:
            if prefix['sector']:
                if sector in prefix['sector']:
                    prefix['relevance'] += RELEVANCE["MATCH_DROPDOWN"]
                    if len(prefix['sector']) == 1:
                        prefix['relevance'] += RELEVANCE["MATCH_DROPDOWN_ONLY_VALUE"]
                else:
                    indexed.pop(prefix['code'], None)
        else:
            if not prefix['sector']:
                prefix['relevance'] += RELEVANCE["MATCH_EMPTY"]

    all_results = {"suggested": [],
                   "recommended": [],
                   "other": []}

    if not indexed:
        return all_results

    for num, value in enumerate(sorted(indexed.values(), key=lambda k: -(k['relevance'] * 100 + k['quality']))):
        if num == 0:
            all_results['suggested'].append(value)
        elif value['relevance'] >= RELEVANCE["RECOMENDED_THRESHOLD"]:
            all_results['recommended'].append(value)
        else:
            all_results['other'].append(value)

    return all_results


def get_lookups(query):
    coverage = query.get('coverage')
    structure = query.get('structure',)
    sector = query.get('sector')
    subnational = query.get('subnational')
    substructure = query.get('substructure')

    coverage_lookups, coverage_all = [], False
    structure_lookups, structure_all = [], False
    sector_lookups, sector_all = [], False
    subnational_lookups = []
    substructure_lookups = []

    valid_lookups = {}

    queries = [{"coverage": '', 'structure': structure, 'sector': sector, 'subnational': subnational, 'substructure': substructure, 'lookups': 'coverage'},
               {"coverage": coverage, 'structure': '', 'sector': sector, 'subnational': subnational, 'substructure': substructure, 'lookups': 'structure'},
               {"coverage": coverage, 'structure': structure, 'sector': sector, 'subnational': subnational, 'substructure': substructure, 'lookups': 'sector'},
               {"coverage": coverage, 'structure': structure, 'sector': sector, 'subnational': '', 'substructure': substructure, 'lookups': 'subnational'},
               {"coverage": coverage, 'structure': structure, 'sector': sector, 'subnational': subnational, 'substructure': '', 'lookups': 'substructure'}]

    for q in queries:
        indexed = {key: value.copy() for key, value in org_id_dict.items()}
        for org_list in list(indexed.values()):

            if q['coverage']:
                if org_list['coverage'] and q['coverage'] not in org_list['coverage']:
                    indexed.pop(org_list['code'], None)
            if q['structure']:
                if org_list['structure'] and q['structure'] not in org_list['structure']:
                    indexed.pop(org_list['code'], None)
            if q['sector']:
                if org_list['sector'] and q['sector'] not in org_list['sector']:
                    indexed.pop(org_list['code'], None)
            if q['subnational']:
                if org_list['subnationalCoverage'] and q['subnational'] not in org_list['subnationalCoverage']:
                    indexed.pop(org_list['code'], None)
            if q['substructure']:
                if org_list['structure'] and q['substructure'] not in org_list['structure']:
                    indexed.pop(org_list['code'], None)

        if q['lookups'] == 'coverage':
            for result in indexed.values():
                if result['coverage']:
                    coverage_lookups.extend([country for country in result['coverage']])
                else:
                    coverage_all = True
                    break
            else:
                coverage_lookups = set(coverage_lookups)
        elif q['lookups'] == 'structure':
            for result in indexed.values():
                if result['structure']:
                    structure_lookups.extend([structure for structure in result['structure']])
                else:
                    structure_all = True
                    break
            else:
                structure_lookups = set(structure_lookups)
        elif q['lookups'] == 'sector':
            for result in indexed.values():
                if result['sector']:
                    sector_lookups.extend([sector for sector in result['sector']])
                else:
                    sector_all = True
                    break
            else:
                sector_lookups = set(sector_lookups)
        elif q['lookups'] == 'subnational' and coverage:
            for result in indexed.values():
                if result['subnationalCoverage']:
                    subnational_lookups.extend([region for region in result['subnationalCoverage']])
            subnational_lookups = set(subnational_lookups)
        elif q['lookups'] == 'substructure' and structure:
            for result in indexed.values():
                if result['structure']:
                    substructure_lookups.extend([structure for structure in result['structure']])
            substructure_lookups = set(substructure_lookups)

    if coverage_all:
        valid_lookups['coverage'] = lookups['coverage']
    else:
        valid_lookups['coverage'] = [tup for tup in lookups['coverage'] if tup[0] in coverage_lookups]

    if structure_all:
        valid_lookups['structure'] = lookups['structure']
    else:
        valid_lookups['structure'] = [tup for tup in lookups['structure'] if tup[0] in structure_lookups]

    if sector_all:
        valid_lookups['sector'] = lookups['sector']
    else:
        valid_lookups['sector'] = [tup for tup in lookups['sector'] if tup[0] in sector_lookups]

    if subnational_lookups and lookups['subnational'].get(coverage):
        valid_lookups['subnational'] = [tup for tup in lookups['subnational'][coverage] if tup[0] in subnational_lookups]
    else:
        valid_lookups['subnational'] = []

    if substructure_lookups and lookups['subnational'].get(structure):
        valid_lookups['substructure'] = [tup for tup in lookups['substructure'][structure] if tup[0] in substructure_lookups]
    else:
        valid_lookups['substructure'] = []

    print(valid_lookups['coverage'])
    print(valid_lookups['structure'])
    print(valid_lookups['sector'])
    print(valid_lookups['subnational'])
    print(valid_lookups['substructure'])


def update_lists(request):
    return HttpResponse(refresh_data())


def home(request):
    query = {key: value for key, value in request.GET.items() if value}
    context = {
        "lookups": {
            'coverage': lookups['coverage'],
            'subnational': [],
            'structure': lookups['structure'],
            'substructure': [],
            'sector': lookups['sector']
        }
    }
    if query:
        # Check for subnational coverage
        if 'coverage' in query:
            subnational = lookups['subnational'].get(query['coverage'])
            context['lookups']['subnational'] = subnational and sorted(subnational) or []
        # Check for substructures
        if 'structure' in query:
            substructures = lookups['substructure'].get(query['structure'])
            context['lookups']['substructure'] = substructures and sorted(substructures) or []
        pass
    else:
        query = {'coverage': '', 'structure': '', 'sector': ''}

    context['query'] = query
    context['all_results'] = filter_and_score_results(query)

    get_lookups(query)

    return render(request, "home.html", context=context)


def list_details(request, prefix):
    try:
        org_list = org_id_dict[prefix]
    except KeyError:
        raise Http404('Organisation list {} does not exist'.format(prefix))
    return render(request, 'list.html', context={'org_list': org_list})
