"""Diagnostic continuity flags; never authorizes aircraft control."""
import math


class ReadingHistory:
    # Broad review thresholds, not aircraft flight envelopes. Keep raw readings.
    limits = {'altitude': (500.,10.), 'airspeed': (100.,5.)}

    def __init__(self):
        self.previous = {}

    def assess(self, instruments, timestamp, processing_seconds=0.):
        result = {}
        for name,(rate_limit,slack) in self.limits.items():
            candidate = instruments[name]
            value = candidate['value']
            prior = self.previous.get(name)
            flag = {'status':'unavailable','value':value,'change_per_second':None,
                    'review_rate_limit':rate_limit,'controls_enabled':False}
            if value is None or not math.isfinite(value):
                result[name] = flag
                continue
            if processing_seconds > 5:
                flag['status'] = 'delayed'
            elif prior is None or timestamp-prior[0] > 10:
                flag['status'] = 'first_reading' if prior is None else 'reacquired'
                self.previous[name] = (timestamp,value,candidate['unit'])
            elif timestamp <= prior[0] or candidate['unit'] != prior[2]:
                flag['status'] = 'incomparable'
            else:
                elapsed = timestamp-prior[0]
                change = value-prior[1]
                flag['change_per_second'] = change/elapsed
                if abs(change) > rate_limit*elapsed+slack:
                    flag['status'] = 'suspicious_jump'
                else:
                    flag['status'] = 'consistent'
                    self.previous[name] = (timestamp,value,candidate['unit'])
            result[name] = flag
        return result
