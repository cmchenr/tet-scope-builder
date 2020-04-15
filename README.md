
# Scope-Builder

Builds a complete multi-tiered Tetration scope tree from column data in an annotation file.

## Installing / Getting started



Python3 - virtual environment (venv) recommended.

Clone this repository.
```shell
git clone https://www.github.com/cmchenr/tet-scope-builder
```


Install necessary pip package dependencies.

```shell
pip install -r requirements.txt
```

Usage:

```shell
python scope_builder.py --help
usage: scope_builder.py [-h] [--tet_url TET_URL] [--tet_creds TET_CREDS]
                        [--tenant TENANT] [--push_scopes PUSH_SCOPES]

Tetration Scope Builder: Required inputs are below. Any inputs not collected
via command line arguments or environment variables will be collected via
interactive prompt.

optional arguments:
  -h, --help            show this help message and exit
  --tet_url TET_URL     Tetration API URL (ex: https://url) - Can
                        alternatively be set via environment variable
                        "SCOPE_BUILDER_TET_URL"
  --tet_creds TET_CREDS
                        Tetration API Credentials File (ex:
                        /User/credentials.json) - Can alternatively be set via
                        environment variable "SCOPE_BUILDER_TET_CREDS"
  --tenant TENANT       Tetration Tenant Name - Can alternatively be set via
                        environment variable "SCOPE_BUILDER_TENANT"
  --push_scopes PUSH_SCOPES
                        Push Scopes - Can alternatively be set via environment
                        variable "SCOPE_BUILDER_PUSH_SCOPES"
```


### Prerequisites

**Tetration API credential JSON file** downloaded from the target Tetration cluster.
Minimum capabilities required are:
* SW Sensor Management
* User, Role and Scope Management

**Annotation File Uploaded to Tetration**
Scope tree columns do not have to be complete.  The scope builder and Tetration both
understand longest-prefix match.

**Abbreviations**
Annotation fields used for scope definition MUST be no longer than 40 characters.
Duplicate fields with same text but case-mismatched will only create a single entry.
The script will try to detect columns that violate the length and
will go through an interactive prompt to allow the user to input abbreviations.  These abbreviations will
be remembered across subsequent runs via the "scopes_config.json" that is saved in the same directory from
which the script is run.  If you would like to update an abbreviation, you can edit the configuration file
directly or you can run "clean.py" to erase and then rebuild your scope tree.


## Usage

User inputs required are:

**Root Scope** - to be used for scope creation.

**Column Names** - The column names associated with each of the tiers in order.