
from common.options import define

# Main

define("host",
       default="http://localhost:9507",
       help="Public hostname of this service",
       type=str)

define("listen",
       default="unix:/usr/local/var/run/anthill/dev_exec.sock",
       help="Socket to listen. Could be a port number (port:N), or a unix domain socket (unix:PATH)",
       type=str)

define("name",
       default="exec",
       help="Service short name. User to discover by discovery service.",
       type=str)

# MySQL database

define("db_host",
       default="localhost",
       type=str,
       help="MySQL database location")

define("db_username",
       default="root",
       type=str,
       help="MySQL account username")

define("db_password",
       default="",
       type=str,
       help="MySQL account password")

define("db_name",
       default="dev_exec",
       type=str,
       help="MySQL database name")

# Regular cache

define("cache_host",
       default="localhost",
       help="Location of a regular cache (redis).",
       group="cache",
       type=str)

define("cache_port",
       default=6379,
       help="Port of regular cache (redis).",
       group="cache",
       type=int)

define("cache_db",
       default=15,
       help="Database of regular cache (redis).",
       group="cache",
       type=int)

define("cache_max_connections",
       default=500,
       help="Maximum connections to the regular cache (connection pool).",
       group="cache",
       type=int)

# JS

define("source_dir",
       default="/opt/local/exec-source",
       help="Directory the source repositories will be pulled into",
       type=str)

define("ssh_private_key",
       default="~/.ssh/id_rsa",
       help="Path to the SSH private key location for pulling source code",
       type=str)

define("ssh_public_key",
       default="~/.ssh/id_rsa.pub",
       help="Path to the SSH public key location for pulling source code (will be provided to the user)",
       type=str)

define("js_call_timeout",
       default=10,
       help="Maximum time limit for each script execution",
       type=int)
