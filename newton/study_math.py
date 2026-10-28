"""Small, deterministic mechanics kernels; no evaluation of generated expressions."""
import math
from devtools.workers import WorkerError

UNITS = {'m': ('length', 1), 'cm': ('length', .01), 'km': ('length', 1000),
         's': ('time', 1), 'min': ('time', 60), 'kg': ('mass', 1), 'g': ('mass', .001),
         'm/s': ('velocity', 1), 'km/h': ('velocity', 1/3.6),
         'm/s^2': ('acceleration', 1), 'm/s²': ('acceleration', 1), 'cm/s^2': ('acceleration', .01),
         'N': ('force', 1), 'kN': ('force', 1000)}
FORMULAS = {
    'average_velocity': ({'displacement': 'length', 'time': 'time'}, 'm/s'),
    'acceleration': ({'initial_velocity': 'velocity', 'final_velocity': 'velocity', 'time': 'time'}, 'm/s^2'),
    'net_force': ({'mass': 'mass', 'acceleration': 'acceleration'}, 'N'),
    'centripetal': ({'speed': 'velocity', 'radius': 'length'}, 'm/s^2'),
}

def number(value, low=-1e6, high=1e6):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise WorkerError('study_invalid_number')
    return float(value)

def quantity(value, dimension):
    if not isinstance(value, dict) or set(value) != {'value', 'unit'} or not isinstance(value['unit'], str):
        raise WorkerError('study_invalid_quantity')
    unit = UNITS.get(value['unit'])
    if not unit or unit[0] != dimension:
        raise WorkerError('study_incorrect_units')
    return number(value['value']) * unit[1]

def calculate(spec):
    if not isinstance(spec, dict) or set(spec) != {'formula', 'inputs'} or not isinstance(spec['formula'], str) or spec['formula'] not in FORMULAS:
        raise WorkerError('study_unsupported_formula')
    name = spec['formula']; dimensions, unit = FORMULAS[name]
    if not isinstance(spec['inputs'], dict) or set(spec['inputs']) != set(dimensions):
        raise WorkerError('study_missing_calculation_input')
    q = {k: quantity(spec['inputs'][k], dimension) for k, dimension in dimensions.items()}
    if ('time' in q and q['time'] <= 0) or ('radius' in q and q['radius'] <= 0) or ('mass' in q and q['mass'] <= 0) or ('speed' in q and q['speed'] < 0):
        raise WorkerError('study_invalid_domain')
    if name == 'average_velocity': value = q['displacement'] / q['time']
    elif name == 'acceleration': value = (q['final_velocity'] - q['initial_velocity']) / q['time']
    elif name == 'net_force': value = q['mass'] * q['acceleration']
    else: value = q['speed'] ** 2 / q['radius']
    if not math.isfinite(value): raise WorkerError('study_invalid_number')
    return {'value': value, 'unit': unit, 'display': f'{value:.6g} {unit}', 'rounding': '6 significant digits for display; full precision for grading', 'method': 'trusted_local_formula'}

def grade(spec, answer):
    expected = calculate(spec)
    dimension = UNITS[expected['unit']][0]
    try:
        actual = quantity(answer, dimension)
    except WorkerError as error:
        return {'correct': False, 'reason': str(error), 'feedback': 'Check the units and enter a finite number.', 'expected': expected}
    correct = math.isclose(actual, expected['value'], rel_tol=.005, abs_tol=1e-8)
    return {'correct': correct, 'reason': 'correct' if correct else 'value_mismatch',
            'feedback': 'The value and units match the local calculation.' if correct else 'The units are compatible; revisit the substitution and arithmetic.',
            'expected': expected, 'tolerance': '0.5% relative or 1e-8 absolute', 'grading': 'local_numeric_not_official_grade'}

def visualization(spec):
    if not isinstance(spec, dict) or set(spec) != {'kind', 'parameters'} or not isinstance(spec['parameters'], dict):
        raise WorkerError('study_invalid_visualization')
    p = spec['parameters']
    if spec['kind'] == 'motion':
        if set(p) != {'position', 'velocity', 'acceleration', 'duration'}: raise WorkerError('study_invalid_visualization')
        x, v, a = (number(p[k], -100, 100) for k in ('position', 'velocity', 'acceleration'))
        duration = number(p['duration'], .1, 60)
        rows = []
        for i in range(61):
            t = duration*i/60
            rows.append({'t': t, 'x': x + v*t + .5*a*t*t, 'v': v+a*t, 'a': a})
        return {'kind': 'motion', 'parameters': p, 'rows': rows, 'units': {'t':'s','x':'m','v':'m/s','a':'m/s²'},
                'assumptions': 'One-dimensional motion with constant acceleration; positive direction is the chosen x axis.',
                'interpretation': 'Slope of position is velocity. Slope of velocity is acceleration. Signed area under velocity gives displacement.',
                'equations': 'x = x₀ + v₀t + ½at²; v = v₀ + at', 'objective': 'Connect position, velocity and acceleration graphs.'}
    if spec['kind'] == 'circular':
        if set(p) != {'speed', 'radius', 'angle'}: raise WorkerError('study_invalid_visualization')
        speed=number(p['speed'],0,30); radius=number(p['radius'],.1,30); angle=math.radians(number(p['angle'],0,360))
        c,s=math.cos(angle),math.sin(angle); acceleration=speed*speed/radius
        return {'kind':'circular', 'parameters':p, 'point':[radius*c,radius*s], 'velocity':[-speed*s,speed*c],
                'acceleration':[-acceleration*c,-acceleration*s], 'magnitude':acceleration,
                'units':{'point':'m','velocity':'m/s','acceleration':'m/s²'},
                'assumptions':'Uniform circular motion in an inertial frame, counterclockwise for positive speed. Fixed radius and speed.',
                'interpretation':'Velocity is tangent; acceleration points inward. Speed stays constant while velocity changes direction.',
                'equations':'a = v²/r; ω = v/r', 'objective':'Distinguish speed from velocity; interpret inward acceleration.',
                'curriculum':'Enrichment: no SPH3U expectation mapping claimed.', 'vector_scale':'Each nonzero arrow has a fixed display length to emphasize direction, not relative magnitude.'}
    raise WorkerError('study_unsupported_visualization')
