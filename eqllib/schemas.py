"""Definitions for analytic metadata and schemas."""
from jsl import DocumentField, ArrayField, StringField, BooleanField, DictField
from jsl import Document as BaseDocument
import jsonschema
import eql.types
from .attack import build_attack, tactics

build_attack()

UUID_PATTERN = r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'
OS_NAMES = ["linux", "macos", "windows"]
TACTICS = [t['name'] for t in tactics]


eql_name = r"[a-zA-Z][A-Za-z0-9_]*"


class Document(BaseDocument):
    """Document with cached schema."""

    __schemas = {}

    @classmethod
    def validate(cls, payload):
        if cls not in Document.__schemas:
            Document.__schemas[cls] = cls.get_schema(ordered=True)
        schema = cls.get_schema(ordered=True)
        jsonschema.validate(payload, schema)
        return payload


class AnalyticMetadata(Document):
    """Base class for all analytics. Can be extended for cloud."""

    id = StringField(pattern=UUID_PATTERN, required=True)
    categories = ArrayField(StringField(enum=['detect', 'hunt', 'enrich']), required=True)
    contributors = ArrayField(StringField(), required=True)
    confidence = StringField(enum=['low', 'medium', 'high'], required=True)
    created_date = StringField(required=True)
    description = StringField(required=True)
    name = StringField(required=True)
    notes = StringField(required=False)
    os = ArrayField(StringField(enum=OS_NAMES), required=True)
    references = ArrayField(StringField(), required=False)
    tactics = ArrayField(StringField(enum=TACTICS), required=False)
    tags = ArrayField(StringField(), required=False)
    techniques = ArrayField(StringField(), required=False)
    updated_date = StringField(required=True)


class Analytic(Document):
    """Schema for an individual analytic."""

    metadata = DocumentField(AnalyticMetadata, required=True, additional_properties=True)
    query = StringField(required=True)


class Domain(Document):
    """Meta schema for defining a query domain."""

    class EventInfo(Document):
        enum = DictField(additional_properties=ArrayField(StringField(eql_name)))
        fields = ArrayField(StringField(eql_name))

    name = StringField(required=True)
    fields = ArrayField(StringField(), required=True)
    events = DictField(additional_properties=DocumentField(EventInfo()))


class StrictDict(DictField):
    """Dictionary schema that does not allow for additional keys."""

    def __init__(self, properties):
        super(StrictDict, self).__init__(properties=properties, additional_properties=False)


class BaseNormalization(Document):
    """Base class for a normalization configuration."""

    domain_name = None

    class TimestampInfo(Document):
        field = StringField(required=True)
        format = StringField(required=True)

    class Fields(Document):
        scope = StringField()
        mapping = DictField()

    name = StringField(required=True)
    filter_query = BooleanField(default=False)
    os_types = ArrayField(StringField(), required=False)
    domain = StringField(required=True)
    strict = BooleanField(required=True)
    timestamp = DocumentField(TimestampInfo(), required=True)
    fields = DocumentField(Fields(), required=True)

    events = DictField(additional_properties=DictField({
        'enum': DictField(additional_properties=DictField(additional_properties=StringField())),
        'mapping': DictField(),
        'filter': StringField(required=True)
    }, required=True))


def make_normalization_schema(domain_schema):
    """Given a domain, make a schema for normalization."""
    class Normalization(BaseNormalization):
        """Normalization schema for a specific domain."""

        eql_schema = domain_to_eql_schema(domain_schema)
        domain_name = domain_schema['name']
        domain = StringField(enum=[domain_name], required=True)

        class Fields(BaseNormalization.Fields):
            mapping = StrictDict({k: StringField() for k in domain_schema['fields']})

        fields = DocumentField(Fields())

        events = DictField({
            event_name: StrictDict({
                'enum': StrictDict({enum_name: StrictDict({enum_option: StringField() for enum_option in enum_options})
                                   for enum_name, enum_options in event_info.get('enum', {}).items()}),
                'mapping': StrictDict({k: StringField() for k in event_info.get('fields', [])}),
                'filter': StringField(required=True)
            })
            for event_name, event_info in domain_schema['events'].items()
        })

    return Normalization


def domain_to_eql_schema(domain, allow_generic=False, allow_any=True):  # type: (dict, bool, bool) -> eql.Schema
    """Given a domain, generate an EQL schema for valid parsing."""
    def mixed_schema(fieldlist):
        return {field: "mixed" for field in fieldlist}

    def make_enum(enum_dict):
        return {field: {value: "boolean" for value in values} for field, values in enum_dict.items()}

    base_fields = domain.get("fields", [])
    full_schema = {}

    for event_name, event_schema in domain.get("events", {}).items():
        full_schema[event_name] = mixed_schema(base_fields)
        full_schema[event_name].update(mixed_schema(event_schema.get("fields", [])))
        full_schema[event_name].update(make_enum(event_schema.get("enum", {})))

    return eql.Schema(full_schema, allow_generic=allow_generic, allow_any=allow_any)
