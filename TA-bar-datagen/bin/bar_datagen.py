import import_declare_test

import sys

from splunklib import modularinput as smi
from bar_datagen_helper import stream_events, validate_input


class BAR_DATAGEN(smi.Script):
    def __init__(self):
        super(BAR_DATAGEN, self).__init__()

    def get_scheme(self):
        scheme = smi.Scheme('bar_datagen')
        scheme.description = 'Bar datagen'
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
                'bar_host',
                required_on_create=True,
            )
        )
        scheme.add_argument(
            smi.Argument(
                'timezone',
                required_on_create=True,
            )
        )
        scheme.add_argument(
            smi.Argument(
                'backfill_days',
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
    exit_code = BAR_DATAGEN().run(sys.argv)
    sys.exit(exit_code)