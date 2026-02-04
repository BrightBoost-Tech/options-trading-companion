import timeit

setup = """
d = {'key': 'value'}
l = [d] * 100000
"""

print("get:", timeit.timeit("for x in l: x.get('key')", setup=setup, number=100))
print("[]:", timeit.timeit("for x in l: x['key']", setup=setup, number=100))
print("try/except:", timeit.timeit("for x in l:\n  try: x['key']\n  except KeyError: pass", setup=setup, number=100))
