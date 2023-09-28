from firebase_admin import firestore
import firebase_admin
import functions_framework
import uuid
import math
from datetime import datetime

def validate_request(request_json):
    request_json['is_missing'] = False
    request_json['is_obsolete'] = False
    request_json['is_confirmed'] = False

    required_fields = {
        "contact_uuid",
        "station_name",
        "date",
        "measurement_type",
        "measurement_value",
    }

    for field in required_fields:
        if field not in request_json:
            return f'Missing {field}'

    measurement_type = request_json['measurement_type']
    if measurement_type not in ['rainfall', 't_max', 't_min']:
        return f'Invalid measurement type "{measurement_type}"'

    return None

def get_uuid():
    return str(uuid.uuid4())

def write_record(request_json):
    db = firestore.client()
    uuid = get_uuid()
    doc_ref = db.collection(u'climate_data').document(uuid)
    doc_ref.set(request_json | {'uuid' : uuid})
    return uuid

def update_record(uuid, request_json):
    db = firestore.client()
    doc_ref = db.collection(u'climate_data').document(uuid)
    if not doc_ref.get().exists:
        return 'Invalid UUID', 200
    doc_ref.set(request_json, merge=True)
    return "Success", 200

def find_records_by_contact(contact_uuid, limit=None):
    limit = limit or 10
    db = firestore.client()
    col_ref = db.collection(u'climate_data')
    q = col_ref.where(u'contact_uuid', u'==', contact_uuid) \
               .where(u'is_obsolete', u'==', False) \
               .order_by('submission_timestamp') \
               .limit_to_last(limit)
    return [doc.to_dict() for doc in q.get()][::-1]

def list_recent_entries(request_json):
    if 'contact_uuid' not in request_json:
        return {'error' : 'No Contact UUID in request'}, 200
    limit = request_json.get('limit')
    try:
        limit = int(limit)
    except:
        limit = None
    docs = find_records_by_contact(request_json['contact_uuid'], limit)
    text = ''
    uuids = []
    records = []
    for i, doc in enumerate(docs):
        measurement_type = doc['measurement_type']
        value = doc['measurement_value']
        text += f"{i+1}. {doc['date']}: {measurement_type} = {value}\n"
        doc['measurement_value'] = str(value)  # RapidPro doesn't like NaN
        records.append(doc)
        uuids.append(doc['uuid'])
    return {'text' : text, 'uuids' : uuids}, 200

def check_existing_records(request_json):
    measurement_type = request_json['measurement_type']
    db = firestore.client()
    col_ref = db.collection(u'climate_data')
    q = col_ref.where(u'date', u'==', request_json['date']) \
               .where(u'contact_uuid', u'==', request_json['contact_uuid']) \
               .where(u'is_obsolete', u'==', False) \
               .where(u'measurement_type', u'==', measurement_type)
    docs = q.stream()
    # If there is a matching record, return it
    for doc in docs:
        return doc.to_dict()
    return None

def check_warnings(request_json):
    measurement_type = request_json['measurement_type']
    if request_json['measurement_value'].lower().strip() in ['m', 'na', 'nan', 'missing']:
        request_json['measurement_value'] = float('nan')
        request_json['is_missing'] = True
        return {}
    try:
        value = float(request_json['measurement_value'])
        request_json['measurement_value'] = value
    except:
        return {'warning' : 'Value is not a number.'}

    if measurement_type == 'rainfall':
        if value < 0:
            return {'warning' : 'Rainfall value must be non-negative.'}
        else:
            return {}

    if measurement_type == 't_min':
        other_type = 't_max'
    else:
        other_type = 't_min'
    record = check_existing_records({'date' : request_json['date'], 'contact_uuid' : request_json['contact_uuid'], 'measurement_type' : other_type})
    if record is None:
        return {}
    other_value = float(record['measurement_value'])
    if math.isnan(other_value):
        return {}
    if measurement_type == 't_max' and value < other_value:
        return {'warning' : f't_max ({value}) < t_min ({other_value}) for this date'}
    elif measurement_type == 't_min' and value > other_value:
        return {'warning' : f't_min ({value}) > t_max ({other_value}) for this date'}
    return {}

def get_or_update_fields(request_json, data_dict):
    if 'uuid' not in request_json:
        return {'error' : 'No UUID in request'}, 200
    uuid = request_json['uuid']
    db = firestore.client()
    doc_ref = db.collection(u'climate_data').document(uuid)
    doc = doc_ref.get()
    if doc.exists:
        if data_dict is not None:
            db.collection(u'climate_data').document(uuid).set(
                data_dict, merge=True
            )
            return {'uuid' : uuid}, 200
        else:
            return doc.to_dict(), 200
    else:
        return {'error' : f'No entry with UUID {uuid} found.'}, 200

def record_entry(request_json, check_existing=True):
    '''
    Check if the request is valid.
    If so, check if there is already a matching record,
        and if so, return it.
    If there is no existing record, write a new record.
    '''
    result = validate_request(request_json)
    if result is not None:
        return {'error' : result}, 200
    if check_existing:
        existing = check_existing_records(request_json)
        if existing is not None:
            # RapidPro doesn't like NaN, so we convert measurement_type
            return {
                    'existing': 'True',
                    'uuid' : existing['uuid'],
                    'measurement_value' : str(existing['measurement_value']),
                    'measurement_type' : existing['measurement_type'],
                    'date' : existing['date']
                }, 200
    warnings = check_warnings(request_json)
    uuid = write_record(request_json | {'submission_timestamp' : str(datetime.utcnow())})
    return {'uuid' : uuid} | warnings, 200

def confirm_entry(request_json):
    return get_or_update_fields(request_json, {'confirmation_timestamp' : str(datetime.utcnow()), 'is_confirmed' : True})

def get_entry(request_json):
    return get_or_update_fields(request_json, data_dict=None)

def update_entry(request_json):
    # This should probably be refactored
    old_uuid = request_json.pop('uuid')
    result = record_entry(request_json, check_existing=False)
    new_uuid = result[0].get('uuid')
    # print(old_uuid, new_uuid)
    if new_uuid:
        result2 = get_or_update_fields(request_json | {'uuid' : old_uuid}, {'obsoleted_by' : new_uuid, 'is_obsolete' : True})
        if 'error' in result2:
            return result[0] | {'warning' : 'New entry written, but ' + result2['error']}, 200
        return result
    else:
        return result


@functions_framework.http
def serve(request):
    """HTTP Cloud Function.
    Args:
        request (flask.Request): The request object.
        <https://flask.palletsprojects.com/en/1.1.x/api/#incoming-request-data>
    Returns:
        The response text, or any set of values that can be turned into a
        Response object using `make_response`
        <https://flask.palletsprojects.com/en/1.1.x/api/#flask.make_response>.
    """
    # request_json = request.get_json(silent=True)
    # request_args = request.args

    request_json = request.get_json(silent=True)
    if not request_json:
        # return 'Hellooo {}!'.format(name)
        return {'error' : 'No Data'}, 200

    path = request.path.strip('/')
    if path == 'record':
        # Returns a json with either an 'error' entry, an 'existing' entry,
        # or a 'uuid' of the new record
        return record_entry(request_json)
    if path == 'confirm':
        # Request should contain a UUID of an existing entry.
        # Updates the entry by adding a confirmation timestamp
        return confirm_entry(request_json)
    if path == 'update':
        # Request should contain a UUID of an existing entry.
        # Updates the entry by adding a obsoleted_by UUID for a new entry that is created.
        return update_entry(request_json)
    if path == 'retrieve':
        # Request should contain a UUID of an existing entry.
        # Returns the entry
        return get_entry(request_json)
    if path == 'list_recent':
        # Request should contain a UUID of a contact (contact_uuid)
        # Returns a list of the 10 most recent submissions by that person:
        # - as text representation
        # - as a list of uuids of the respective entries
        # - as a list of the complete records
        return list_recent_entries(request_json)
    else:
        return {'error' : 'Invalid path'}, 200

# Application Default credentials are automatically created.
app = firebase_admin.initialize_app()
