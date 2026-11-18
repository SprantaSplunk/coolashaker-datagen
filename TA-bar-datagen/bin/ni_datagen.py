import import_declare_test

import sys

from splunklib import modularinput as smi
from ni_datagen_helper import stream_events, validate_input


class NI_DATAGEN(smi.Script):
    def __init__(self):
        super(NI_DATAGEN, self).__init__()

    def get_scheme(self):
        scheme = smi.Scheme('ni_datagen')
        scheme.description = 'Network Intelligence (Meraki, Catalyst Center, ThousandEyes, SC4SNMP)'
        scheme.use_external_validation = True
        scheme.streaming_mode_xml = True
        scheme.use_single_instance = False

        scheme.add_argument(
            smi.Argument(
                'name',
                title='Name',
                description='Name',
                required_on_create=True
            )
        )
        scheme.add_argument(
            smi.Argument(
                'seed',
                required_on_create=True,
            )
        )
        scheme.add_argument(
            smi.Argument(
                'index_meraki',
                required_on_create=True,
            )
        )
        scheme.add_argument(
            smi.Argument(
                'index_catalyst',
                required_on_create=True,
            )
        )
        scheme.add_argument(
            smi.Argument(
                'index_thousandeyes',
                required_on_create=True,
            )
        )
        scheme.add_argument(
            smi.Argument(
                'index_snmp',
                required_on_create=True,
            )
        )
        scheme.add_argument(
            smi.Argument(
                'index_summary',
                required_on_create=True,
            )
        )
        scheme.add_argument(
            smi.Argument(
                'alert_backfill_hours',
                required_on_create=True,
            )
        )
        scheme.add_argument(
            smi.Argument(
                'backfill_hours',
                required_on_create=True,
            )
        )
        scheme.add_argument(
            smi.Argument(
                'summary_backfill_hours',
                required_on_create=True,
            )
        )
        scheme.add_argument(
            smi.Argument(
                'max_gap_minutes',
                required_on_create=True,
            )
        )
        return scheme

    def validate_input(self, definition: smi.ValidationDefinition):
        return validate_input(definition)

    def stream_events(self, inputs: smi.InputDefinition, ew: smi.EventWriter):
        return stream_events(inputs, ew)


if __name__ == '__main__':
    exit_code = NI_DATAGEN().run(sys.argv)
    sys.exit(exit_code)