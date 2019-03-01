"""
Copyright (c) 2018 Cisco and/or its affiliates.
This software is licensed to you under the terms of the Cisco Sample
Code License, Version 1.0 (the "License"). You may obtain a copy of the
License at
               https://developer.cisco.com/docs/licenses
All use of the material herein must be in accordance with the terms of
the License. All rights not expressly granted by the License are
reserved. Unless required by applicable law or agreed to separately in
writing, software distributed under the License is distributed on an "AS
IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express
or implied.
"""

__author__ = "Chris McHenry"
__copyright__ = "Copyright (c) 2018 Cisco and/or its affiliates."
__license__ = "Cisco Sample Code License, Version 1.0"

import pandas as pd
import numpy as np
import urllib3
import ipaddress
from tetpyclient import RestClient
import json
import re
import argparse
import getpass
import os

def create_scope(parent,scope_name,tag_name,tag_value,rc):
    req_payload = {
                        "short_name": "{}".format(scope_name),
                        "short_query": {
                            "type":"eq",
                            "field": "user_{}".format(tag_name),
                            "value": "{}".format(tag_value)
                        },
                        "parent_app_scope_id": "{}".format(parent)
                    }
    resp = rc.post("/app_scopes", json_body=json.dumps(req_payload))
    scope = resp.json()
    if resp.status_code != 200:
        print(resp.json())
        return 1
    return scope['id']

def get_columns():
    print('''
Please input the columns that you would like to use to create the scope tree.  The columns should be comma delimited and in order. The order will determine which level of the tree a column represents.
ex: Region, Security Zone, Application, Lifecycle
    ''')
    columns = []
    for column in raw_input('Scope Levels: ').split(','):
        columns.append(column.strip())
    confirmation = False
    while confirmation == False:
        r = raw_input('You selected {}. Would you like to use these (Y,N)?:'.format(json.dumps(columns)))
        if r.lower() == 'y' or r.lower() == 'yes':
            confirmation = True
        elif r.lower() == 'n' or r.lower() == 'no':
            columns = get_columns()
            confirmation = True
    return columns

def supernet(ip,prefix):
    address = ipaddress.ip_network(unicode(ip))
    if address.prefixlen > prefix:
        return str(address.supernet(new_prefix=prefix).with_prefixlen)
    else:
        return np.nan

def common_abbreviations(scopes, abbreviations):
    print('Checking abbreviations for common scope layers...')
    total = len(scopes)
    for column in scopes.columns:
        if column != 'IP':
            values = scopes[column].unique()
            if float(len(values))/total < .1:
                if column not in abbreviations:
                    abbreviations[column] = {}
                for item in values:
                    if item not in abbreviations[column]:
                        r = raw_input('Create an abbreviation for Value: "{}" in Column: "{}" (Leave blank if none desired):'.format(item,column))
                        if len(r) > 0:
                            abbreviations[column][item]=r
                        else:
                            abbreviations[column][item]=None
            

def shorten_scope(root_scope_name,scope,abbreviations):
    shortened_columns = []
    for index in scope.index:
        if index in abbreviations:
            if scope[index] in abbreviations[index] and abbreviations[index][scope[index]] != None:
                scope[index] = abbreviations[index][scope[index]]
                shortened_columns.append(index)

    scope_long_name = ':'.join([root_scope_name]+list(scope))
    if len(scope_long_name) > 40:
        for attribute in scope.index:
            if attribute not in shortened_columns:
                if attribute not in abbreviations:
                    abbreviations[attribute]={}
                if scope[attribute] not in abbreviations[attribute]:
                    r = raw_input('This scope is too long.  Please create an abbreviation for Value: "{}" in Column: "{}" (Leave blank if none desired):'.format(scope[attribute],attribute))
                    if len(r) > 0:
                        abbreviations[attribute][scope[attribute]]=r
                        scope[attribute]=r
                    else:
                        abbreviations[attribute][scope[attribute]]=None
    return scope

def build_scopes(site_config, tenant_config):
    # Create Tetration API RestClient
    rc = RestClient(site_config['url'], credentials_file=site_config['creds'], verify=False)
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    root_scope_name = site_config['tenant']
    columns = tenant_config['columns']

    # Download Annotations File for Root Scope and Load into Pandas Data Frame
    file_path = '/tmp/temp_annotations.csv'
    rc.download(file_path, '/assets/cmdb/download/' + root_scope_name)
    df = pd.read_csv("/tmp/temp_annotations.csv")

    # Filter Annotations to only the relevant columns and entries witn non-null values in at least one of the columns
    print(df.columns)
    df=df[columns+['IP']].set_index('IP').dropna(how='all').reset_index()

    ## Collapse longest prefix match tags
    subnets=df[df['IP'].str.contains('/')].rename(columns={'IP':'Subnet'})
    subnets['Mask']=subnets['Subnet'].apply(lambda x: int(x.split('/')[1]))
    prefix_list = list(subnets['Mask'].unique())
    prefix_list.sort(reverse=True)
    subnets.drop(columns='Mask',inplace=True)
    for prefix in prefix_list:
        df['Subnet']=df['IP'].apply(lambda x: supernet(x,prefix))
        if not df['Subnet'].isnull().all():
            merged = pd.merge(subnets,df[['IP','Subnet']],on='Subnet').set_index('IP')
            df = df.set_index('IP').combine_first(merged).reset_index()

    ## Create scope list from annotations file
    scopes = df.replace(np.nan,"nan").groupby(columns)['IP'].apply(list)
    scopes=scopes.reset_index().replace('nan',np.nan)

    ## Gather existing scopes and IDs
    scope_ids = {}
    resp = rc.get('/openapi/v1/app_scopes/')
    if resp.status_code == 200:
        current_scopes = resp.json()
        root_scope = [x for x in current_scopes if x['name'] == root_scope_name]
        if len(root_scope)>0:
            root_scope_id = root_scope[0]['id']
            current_scopes = [x for x in current_scopes if x['root_app_scope_id'] == root_scope_id]
            for scope in current_scopes:
                scope_ids[scope['name']]=scope['id']

    ## Build common abbreviations
    common_abbreviations(scopes, tenant_config['abbreviations'])
    inv_abbreviations={}
    for item in tenant_config['abbreviations']:
        inv_abbreviations[item] = {v: k for k, v in tenant_config['abbreviations'][item].iteritems()}
    print(inv_abbreviations)
    
    ## Create new scopes
    errors = []
    i = 0
    while i < len(scopes):
        root_scope_name = site_config['tenant']
        parent = root_scope_name
        scope = scopes.iloc[i].dropna().drop(labels=['IP'])
        scope = shorten_scope(root_scope_name,scope,tenant_config['abbreviations'])
        scope_long_name = ':'.join([root_scope_name]+list(scope))
        if len(scope_long_name)>40:
            errors.append(scope_long_name)
        for attribute in scope.index:
            scope_name = parent + ':' + scope[attribute].strip()
            if not scope_name in scope_ids:
                if site_config['push_scopes']:
                    print('[CREATING SCOPE]: {}'.format(scope_name))
                    if scope[attribute] in inv_abbreviations[attribute]:
                        value = inv_abbreviations[attribute][scope[attribute]]
                    else:
                        value = scope[attribute]
                    scope_ids[scope_name]=create_scope(parent=scope_ids[parent],scope_name=scope[attribute],tag_name=attribute,tag_value=value,rc=rc)
                else:
                    print('[NEW SCOPE]: {}'.format(scope_name))
                    scope_ids[scope_name]=1
            #else:
                #print('[EXISTING SCOPE]: {}'.format(scope_name))
            parent=scope_name
        i+=1

    print(json.dumps(errors))

def main():
    """
    Main execution routine
    """
    conf_vars = {
                'tet_url':{
                    'descr':'Tetration API URL (ex: https://url)',
                    'env':'SCOPE_BUILDER_TET_URL',
                    'conf':'url'
                    },
                'tet_creds':{
                    'descr':'Tetration API Credentials File (ex: /User/credentials.json)',
                    'env':'SCOPE_BUILDER_TET_CREDS',
                    'conf':'creds',
                    'alt':['tet_api_key','tet_api_secret']
                    },
                'tenant':{
                    'descr':'Tetration Tenant Name',
                    'env':'SCOPE_BUILDER_TENANT',
                    'conf':'tenant'
                    },
                'push_scopes':{
                    'descr':'Push Scopes',
                    'env':'SCOPE_BUILDER_PUSH_SCOPES',
                    'conf':'push_scopes',
                    'default':False
                    }
                }
    
    parser = argparse.ArgumentParser(description='Tetration Scope Builder: Required inputs are below.  Any inputs not collected via command line arguments or environment variables will be collected via interactive prompt.')
    for item in conf_vars:
        descr = conf_vars[item]['descr']
        if 'env' in conf_vars[item]:
            descr = '{} - Can alternatively be set via environment variable "{}"'.format(conf_vars[item]['descr'],conf_vars[item]['env'])
        default = None
        if 'default' in conf_vars[item]:
            default = conf_vars[item]['default']
        elif 'env' in conf_vars[item]:
            default = os.environ.get(conf_vars[item]['env'], None)
        parser.add_argument('--'+item,default=default,help=descr)
    args = parser.parse_args()

    site_config = {}
    for arg in vars(args):
        attribute = getattr(args, arg)
        if attribute == None:
            if 'hidden' in conf_vars[arg]:
                site_config[conf_vars[arg]['conf']] = getpass.getpass('{}: '.format(conf_vars[arg]['descr']))
            else:
                site_config[conf_vars[arg]['conf']] = raw_input('{}: '.format(conf_vars[arg]['descr']))
        else:
            site_config[conf_vars[arg]['conf']] = attribute

    try:
        with open('./scopes_config.json') as f:
            scopes_config = json.load(f)
            print('Previous configuration loaded.')
    except:
        scopes_config = {}
        print('No previous configuration loaded.')
    
    if site_config['tenant'] in scopes_config:
        tenant_config = scopes_config[site_config['tenant']]
    else:
        tenant_config = {'columns':[],'abbreviations':{}}
    
    if len(tenant_config['columns']) == 0:
        tenant_config['columns'] = get_columns()
    else:
        print('Previous column configuration found.  Using {} to build scope tree.'.format(json.dumps(tenant_config['columns'])))

    build_scopes(site_config,tenant_config)

    scopes_config[site_config['tenant']] = tenant_config
    with open('./scopes_config.json', 'w') as outfile:
        json.dump(scopes_config, outfile, indent=1)

if __name__ == '__main__':
    main()