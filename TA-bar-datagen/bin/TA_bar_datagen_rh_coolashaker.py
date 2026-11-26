
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
        default='60',
        validator=validator.AllOf(
            validator.Pattern(
                regex=r"""^((?:-1|\d+(?:\.\d+)?)|(([\*\d{1,2}\,\-\/]+\s){4}[\*\d{1,2}\,\-\/]+))$""", 
            ), 
            validator.Number(
                max_val=300, 
                min_val=30, 
            )
        )
    ), 
    field.RestField(
        'volume',
        required=True,
        encrypted=False,
        default='reduced',
        validator=None
    ), 
    field.RestField(
        'cs_host',
        required=True,
        encrypted=False,
        default='coolashaker',
        validator=validator.Pattern(
            regex=r"""^[\w.-]+$""", 
        )
    ), 
    field.RestField(
        'timezone',
        required=True,
        encrypted=False,
        default='Europe/Vienna',
        validator=validator.Pattern(
            regex=r"""^[A-Za-z_]+(/[A-Za-z_+-]+)*$""", 
        )
    ), 
    field.RestField(
        'backfill_minutes',
        required=True,
        encrypted=False,
        default='0',
        validator=validator.Number(
            max_val=10080, 
            min_val=0, 
        )
    ), 
    field.RestField(
        'max_gap_minutes',
        required=True,
        encrypted=False,
        default='15',
        validator=validator.Number(
            max_val=1440, 
            min_val=0, 
        )
    ), 
    field.RestField(
        'scenario_dc_frankfurt',
        required=False,
        encrypted=False,
        default=0,
        validator=None
    ), 
    field.RestField(
        'scenario_sdwan_brownout',
        required=False,
        encrypted=False,
        default=0,
        validator=None
    ), 
    field.RestField(
        'scenario_isp_route_leak',
        required=False,
        encrypted=False,
        default=0,
        validator=None
    ), 
    field.RestField(
        'scenario_berlin_db',
        required=False,
        encrypted=False,
        default=0,
        validator=None
    ), 
    field.RestField(
        'scenario_berlin_dos',
        required=False,
        encrypted=False,
        default=0,
        validator=None
    ), 
    field.RestField(
        'scenario_atlanta_teams',
        required=False,
        encrypted=False,
        default=0,
        validator=None
    ), 
    field.RestField(
        'scenario_vienna_teams',
        required=False,
        encrypted=False,
        default=0,
        validator=None
    ), 
    field.RestField(
        'scenario_atlanta_network',
        required=False,
        encrypted=False,
        default=0,
        validator=None
    ), 
    field.RestField(
        'scenario_sap_idoc',
        required=False,
        encrypted=False,
        default=0,
        validator=None
    ), 

    field.RestField(
        'disabled',
        required=False,
        validator=None
    )

]
model = RestModel(fields, name=None, special_fields=special_fields)



endpoint = DataInputModel(
    'coolashaker',
    model,
)


if __name__ == '__main__':
    logging.getLogger().addHandler(logging.NullHandler())
    admin_external.handle(
        endpoint,
        handler=AdminExternalHandler,
    )
