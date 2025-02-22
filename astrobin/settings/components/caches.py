import os

CACHE_TYPE = os.environ.get('CACHE_TYPE', 'redis').strip()

if CACHE_TYPE == 'redis':
    CACHES = {
        'default': {
            'BACKEND': 'django_redis.cache.RedisCache',
            'LOCATION': os.environ.get('CACHE_URL', 'redis://redis:6379/1').strip(),
            'OPTIONS': {
                'CLIENT_CLASS': 'django_redis.client.DefaultClient',
                'PICKLE_VERSION': 2,
                'SERIALIZER':'astrobin.cache.CustomPickleSerializer',
            },
            'KEY_PREFIX': 'astrobin'
        }
    }
elif CACHE_TYPE == 'locmem':
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        }
    }
else:
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.dummy.DummyCache',
        }
    }
