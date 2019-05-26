#!/usr/bin/python
import socket
import fcntl
import struct

def get_iphostname():
    '''??linux?????????IP??'''
    def get_ip(ifname):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM) 
        ipaddr = socket.inet_ntoa(fcntl.ioctl(
                            sock.fileno(), 
                            0x8915,  # SIOCGIFADDR 
                            struct.pack('256s', ifname[:15]) 
                            )[20:24]
                            )   
        sock.close()
        return ipaddr
    try:
        ip = get_ip('eth0')
    except IOError:
        ip = get_ip('eno1')
    hostname = socket.gethostname()
    return {'hostname': hostname, 'ip':ip} 

get_iphostname()
