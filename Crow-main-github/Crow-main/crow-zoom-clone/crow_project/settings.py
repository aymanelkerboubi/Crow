# settings.py

# REMOVE the 'InMemoryChannelLayer' block entirely.
# KEEP only this one:
CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels_redis.core.RedisChannelLayer',
        'CONFIG': {
            "hosts": [('127.0.0.1', 6379)],
        },
    },
}
# settings.py

DEBUG = True
ALLOWED_HOSTS = ['*']  # Allows you to access the site via 127.0.0.1 or localhost