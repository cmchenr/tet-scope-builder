import urllib3
import ipaddress
from tetpyclient import RestClient
import json
import os

restclient = RestClient(os.environ.get('SCOPE_BUILDER_TET_URL', None), credentials_file=os.environ.get('SCOPE_BUILDER_TET_CREDS', None), verify=False)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

errors = []
root_scope_name = os.environ.get('SCOPE_BUILDER_PUSH_SCOPES', None)

## Gather existing scopes and IDs
scope_ids = {}
resp = restclient.get('/openapi/v1/app_scopes/')
if resp.status_code == 200:
    current_scopes = resp.json()
    root_scope = [x for x in current_scopes if x['name'] == root_scope_name]
    app_scope_id = root_scope[0]['id']
    vrf_id = root_scope[0]['query']['value']

# -------------------------------------------------------------------------
# DETERMINE SCOPES TO BE DELETED
# Using two lists here as queues:
# 1. toBeExamined is a FIFO where we add parent scopes at position zero and
#    use pop to remove them from the end. We add one entire heirarchical
#    level of parents before we add a single one of their children. This
#    process will continue until there are no more children to add and the
#    FIFO will eventually be empty.
# 2. toBeDeleted is a LIFO where we append parent scopes at the end before
#    we append their children. Later, we will pop scopes from the end when
#    deleting them, so child scopes will always be deleted before their
#    parents (which is required by Tetration).

print "[CHECKING] all scopes in Tetration."
toBeDeleted = []
toBeExamined = [ app_scope_id ]
while len(toBeExamined):
    scopeId = toBeExamined.pop()
    resp = restclient.get('/openapi/v1/app_scopes/' + scopeId)
    if resp.status_code == 200:
        for scope in resp.json()["child_app_scope_ids"]:
            toBeExamined.insert(0, scope)
            toBeDeleted.append(scope)
    else:
        print "[ERROR] examining scope '{}'. This will cause problems deleting all scopes.".format(scopeId)
        errors.append("[ERROR] examining scope '{}'. This will cause problems deleting all scopes.".format(scopeId))
        print resp, resp.text

# -------------------------------------------------------------------------
# DELETE THE WORKSPACES
# Walk through all applications and remove any in a scope that should be
# deleted. In order to delete an application, we have to turn off enforcing
# and make it secondary first.

resp = restclient.get('/openapi/v1/applications/')
if resp.status_code == 200:
    resp_data = resp.json()
else:
    print "[ERROR] reading application workspaces to determine which ones should be deleted."
    errors.append("[ERROR] reading application workspaces to determine which ones should be deleted.")
    print resp, resp.text
    resp_data = {}
for app in resp_data:
    appName = app["name"]
    if app["app_scope_id"] in toBeDeleted or app["app_scope_id"] == app_scope_id:
        app_id = app["id"]
        # first we turn off enforcement
        if app["enforcement_enabled"]:
            r = restclient.post('/openapi/v1/applications/' + app_id + '/disable_enforce')
            if r.status_code == 200:
                print "[CHANGED] app {} ({}) to not enforcing.".format(app_id, appName)
            else:
                print "[ERROR] changing app {} ({}) to not enforcing. Trying again...".format(app_id, appName)
                time.sleep(1)
                r = restclient.post('/openapi/v1/applications/' + app_id + '/disable_enforce')
                if r.status_code == 200:
                    print "[CHANGED] app {} ({}) to not enforcing.".format(app_id, appName)
                else:
                    errors.append("[ERROR] Failed again. Details: {} -- {}".format(resp,resp.text))
                    print resp, resp.text
        # make the application secondary if it is primary
        if app["primary"]:
            req_payload = {"primary": "false"}
            r = restclient.put('/openapi/v1/applications/' + app_id, json_body=json.dumps(req_payload))
            if r.status_code == 200:
                print "[CHANGED] app {} ({}) to secondary.".format(app_id, appName)
            else:
                #Wait and try again
                print "[ERROR] changing app {} ({}) to secondary. Trying again...".format(app_id, appName)
                time.sleep(1)
                r = restclient.post('/openapi/v1/applications/' + app_id + '/disable_enforce')
                if r.status_code == 200:
                    print "[CHANGED] app {} ({}) to not enforcing.".format(app_id, appName)
                else:
                    errors.append("[ERROR] Failed again. Details: {} -- {}".format(resp,resp.text))
                    print resp, resp.text
        # now delete the app
        r = restclient.delete('/openapi/v1/applications/' + app_id)
        if r.status_code == 200:
            print "[REMOVED] app {} ({}) successfully.".format(app_id, appName)
        else:
            #Wait and try again
            print "[ERROR] deleting {} ({}). Trying again...".format(app_id, appName)
            time.sleep(1)
            r = restclient.delete('/openapi/v1/applications/' + app_id)
            if r.status_code == 200:
                print "[REMOVED] app {} ({}) successfully.".format(app_id, appName)
            else:
                errors.append("[ERROR] Failed again. Details: {} -- {}".format(resp,resp.text))
                print resp, resp.text

# -------------------------------------------------------------------------
# DETERMINE ALL FILTERS ASSOCIATED WITH THIS VRF_ID
# Inventory filters have a query that the user enters but there is also a
# query for the vrf_id to match. So we simply walk through all filters and
# look for that query to match this vrf_id... if there is a match then
# mark the filter as a target for deletion.  Before deleting filters, 
# we need to delete the agent config intents

filtersToBeDeleted = []

resp = restclient.get('/openapi/v1/filters/inventories')
if resp.status_code == 200:
    resp_data = resp.json()
else:
    print "[ERROR] reading filters to determine which ones should be deleted."
    errors.append("[ERROR] reading filters to determine which ones should be deleted.")
    print resp, resp.text
    resp_data = {}
for filt in resp_data:
    try:
        inventory_filter_id = filt["id"]
        filterName = filt["name"]
        for query in filt["query"]["filters"]:
            if 'field' in query.iterkeys() and query["field"] == "vrf_id" and query["value"] == int(vrf_id):
                filtersToBeDeleted.append({'id':inventory_filter_id,'name':filterName})
    except:
        print(json.dumps(filt))

            
# -------------------------------------------------------------------------
# DELETE AGENT CONFIG INTENTS
# Look through all agent config intents and delete instances that are based
# on a filter or scope in filtersToBeDeleted or toBeDeleted (scopes)

print "[CHECKING] all inventory config intents in Tetration."

resp = restclient.get('/openapi/v1/inventory_config/intents')
if resp.status_code == 200:
    resp_data = resp.json()
else:
    print "[ERROR] reading inventory config intents to determine which ones should be deleted."
    errors.append("[ERROR] reading inventory config intents to determine which ones should be deleted.")
    print resp, resp.text
    resp_data = {}
for intent in resp_data:
    intent_id = intent['id']
    filter_id = intent["inventory_filter_id"]
    if filter_id in filtersToBeDeleted or filter_id in toBeDeleted or filter_id == app_scope_id:
        r = restclient.delete('/openapi/v1/inventory_config/intents/' + intent_id)
        if r.status_code == 200:
            print "[REMOVED] inventory config intent {}.".format(intent_id)
        else:
            print "[ERROR] removing inventory config intent {}.".format(intent_id)
            errors.append("[ERROR] removing inventory config intent {}.".format(intent_id))
            print r, r.text


# -------------------------------------------------------------------------
# DELETE THE FILTERS

while len(filtersToBeDeleted):
    filterId = filtersToBeDeleted.pop()
    r = restclient.delete('/openapi/v1/filters/inventories/' + filterId['id'])
    if r.status_code == 200:
        print "[REMOVED] inventory filter {} named '{}'.".format(filterId['id'], filterId['name'])
    else:
        print "[ERROR] removing inventory filter {} named '{}'.".format(filterId['id'], filterId['name'])
        errors.append("[ERROR] removing inventory filter {} named '{}'.".format(filterId['id'], filterId['name']))
        print r, r.text


# -------------------------------------------------------------------------
# DELETE THE SCOPES

while len(toBeDeleted):
    scopeId = toBeDeleted.pop()
    resp = restclient.delete('/openapi/v1/app_scopes/' + scopeId)
    if resp.status_code == 200:
        print "[REMOVED] scope {} successfully.".format(scopeId)
    else:
        print "[ERROR] removing scope {}.".format(scopeId)
        errors.append("[ERROR] removing scope {}.".format(scopeId))
        print resp, resp.text