import os

os.environ.setdefault("PROVISIONER_API_KEY", "test-key")
os.environ.setdefault("PUBLIC_SIP_URI", "sip:asterisk.test:5061;transport=tls")
os.environ.setdefault("LIVEKIT_SIP_URI", "sip:livekit.test:5061;transport=tls")
os.environ.setdefault("AMI_USERNAME", "provisioner")
os.environ.setdefault("AMI_PASSWORD", "secret")
