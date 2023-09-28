# E-PICSA Data recorder

A chatbot for recording climate data in a database.

There are multiple components:

- The database, storing entered data. We use Google Firestore for this.
- An API to add new entries and query existing entries. This uses Google Cloud functions.
- The chatbot flows, making calls to this API via webhooks. This is done in RapidPro.

## Functionality

Query URLs support the following paths:

- `record`: (new entry data) Record a new entry (creates a new entry)
- `confirm` (uuid): Verify an entry (adds a confirmation_timestamp)
- `update` (uuid, new entry data): Record a new entry and obsolete the entry with `uuid` (adds `obsoleted_by`)
- `retrieve` (uuid): Retrieve an entry
- `list_recent` (contact_uuid, limit): Returns `limit` most recent entries submitted by `contact_uuid`

Firestore entries have a uuid and contain

- `contact_uuid`: RapidPro uuid of the contact who submitted the entry
- `station_name`: Name of the station that the contact is reporting for.
- `date`: Date of the measurement (child.results.measurement_date)?
- `submission_timestamp`: Timestamp when the entry was added to the DB
- `measurement_type`: The type of measurement. Either `t_max` (maximum temperature in Celsius), `t_min` (minimum temperature in Celsius) or `rainfall` (rainfall in mm).
- `measurement_value`: measurement on the date `date` for the station `station_name`
- `is_missing`: `True` if the value is `NaN`, `False` otherwise.
- `is_confirmed`: `True` value has been confirmed, `False` otherwise.
- `is_obsolete`: `True` if the entry is obsolete (because an updated entry has been submitted), `False` otherwise.
- `confirmation_timestamp`: Whether the submitter has verified the data (Optional)
- `obsoleted_by`: UUID of the entry which makes this entry obsolete. This is used if a user updates an entry. This way, we keep a record of changes made. (Optional)

Note: `is_missing`, `is_confirmed` and `is_obsolete` would be redundant in a relational database, but Firebase only allows querying one field at a time for inequality, so we add these entries to make querying easier.

Sanity checks that are done when recording a new entry:

- Does the entry already exist? If yes, don't update, but return UUID of found entry to request confirmation of overwrite.
- tmax >= tmin? If not, save the value, but return a warning.
- rainfall >= 0? If not, save the value, but return a warning.

## How to deploy

https://cloud.google.com/functions/docs/deploy

Two options: 

- Either edit the code directly via the UI
- Or deploy via console (recommended).

### Console deployment

#### First-time setup

Follow these steps:
- https://cloud.google.com/sdk/docs/install
- https://cloud.google.com/sdk/docs/initializing

In Firestore:

- Create collection `climate_data`
- Create an index in this collection where `contact_uuid` and `is_obsolete` are ASC and `submission_timestamp` and `__name__` are DESC.

#### Deploy after code changes

```
gcloud config set project <id of your project>
gcloud functions deploy record-climate-data \
--gen2 \
--region=<region of your cloud function> \
--runtime=python311 \
--source=. \
--entry-point=serve \
--trigger-http
```

## TODOS

- Upload the flows
- Secure the Cloud function through an Authorization token or password
- Ensure `update` doesn't create a duplicate entry (same date, same type)
- After warnings, allow user to directly edit the entry.