

backlog = 64
timeout = 10*60
pidfile = '/app/logs/gunicorn.pid'

access_log_format = (
    '{' 
    '"remote_addr": "%(h)s",' 
    '"remote_user": "%(u)s",' 
    '"local_time": "%(t)s",' 
    '"request": "%(r)s",' 
    '"status": "%(s)s",' 
    '"bytes_sent": %(b)s,' 
    '"referer": "%(f)s",' 
    '"user_agent": "%(a)s",' 
    '"upstream_request_time": %(D)s,' 
    '"process_id": "%(p)s"' 
    '}'
)

# FOR DEBUGGING
# workers = 1
# capture_output = True
# accesslog = "-"
# errorlog = "-"

# FOR PRODUCTION
workers = 5
accesslog = "/app/logs/gunicorn_access.log"
errorlog = "/app/logs/gunicorn_error.log"
logfile = "/app/logs/gunicorn_debug.log"

