
import import_declare_test

from splunktaucclib.rest_handler.endpoint import (
    field,
    validator,
    RestModel,
    DataInputModel,
)
from splunktaucclib.rest_handler import admin_external, util
from splunktaucclib.rest_handler.admin_external import AdminExternalHandler
import logging

util.remove_http_proxy_env_vars()


special_fields = [
    field.RestField(
        'name',
        required=True,
        encrypted=False,
        default=None,
        validator=validator.AllOf(
            validator.Pattern(
                regex=r"""^[a-zA-Z]\w*$""", 
            ), 
            validator.String(
                max_len=100, 
                min_len=1, 
            )
        )
    )
]

fields = [
    field.RestField(
        'interval',
        required=True,
        encrypted=False,
        default='300',
        validator=validator.AllOf(
            validator.Pattern(
                regex=r"""^((?:-1|\d+(?:\.\d+)?)|(([\*\d{1,2}\,\-\/]+\s){4}[\*\d{1,2}\,\-\/]+))$""", 
            ), 
            validator.Number(
                max_val=3600, 
                min_val=60, 
            )
        )
    ), 
    field.RestField(
        'seed',
        required=True,
        encrypted=False,
        default='2690',
        validator=validator.Number(
            max_val=999999, 
            min_val=1, 
        )
    ), 
    field.RestField(
        'index_meraki',
        required=True,
        encrypted=False,
        default='demo_cisco_meraki',
        validator=validator.Pattern(
            regex=r"""^[a-z0-9_][a-z0-9_-]*$""", 
        )
    ), 
    field.RestField(
        'index_catalyst',
        required=True,
        encrypted=False,
        default='demo_cisco_catalyst',
        validator=validator.Pattern(
            regex=r"""^[a-z0-9_][a-z0-9_-]*$""", 
        )
    ), 
    field.RestField(
        'index_thousandeyes',
        required=True,
        encrypted=False,
        default='demo_thousendeyes',
        validator=validator.Pattern(
            regex=r"""^[a-z0-9_][a-z0-9_-]*$""", 
        )
    ), 
    field.RestField(
        'index_snmp',
        required=True,
        encrypted=False,
        default='netops',
        validator=validator.Pattern(
            regex=r"""^[a-z0-9_][a-z0-9_-]*$""", 
        )
    ), 
    field.RestField(
        'index_summary',
        required=True,
        encrypted=False,
        default='ni_capability_summary',
        validator=validator.Pattern(
            regex=r"""^[a-z0-9_][a-z0-9_-]*$""", 
        )
    ), 
    field.RestField(
        'alert_backfill_hours',
        required=True,
        encrypted=False,
        default='48',
        validator=validator.Number(
            max_val=168, 
            min_val=0, 
        )
    ), 
    field.RestField(
        'backfill_hours',
        required=True,
        encrypted=False,
        default='2',
        validator=validator.Number(
            max_val=48, 
            min_val=0, 
        )
    ), 
    field.RestField(
        'summary_backfill_hours',
        required=True,
        encrypted=False,
        default='24',
        validator=validator.Number(
            max_val=168, 
            min_val=0, 
        )
    ), 
    field.RestField(
        'max_gap_minutes',
        required=True,
        encrypted=False,
        default='30',
        validator=validator.Number(
            max_val=1440, 
            min_val=0, 
        )
    ), 

    field.RestField(
        'disabled',
        required=False,
        validator=None
    )

]
model = RestModel(fields, name=None, special_fields=special_fields)



endpoint = DataInputModel(
    'ni_datagen',
    model,
)


if __name__ == '__main__':
    logging.getLogger().addHandler(logging.NullHandler())
    admin_external.handle(
        endpoint,
        handler=AdminExternalHandler,
    )
