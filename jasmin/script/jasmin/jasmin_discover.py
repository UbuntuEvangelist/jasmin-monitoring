#!/usr/bin/python
# This a script is called by Zabbix agent to discover users and smppcs

import json, struct, time, argparse, re, socket, sys
from lockfile import FileLock, LockTimeout, AlreadyLocked
from telnetlib import Telnet, IAC, DO, DONT, WILL, WONT, SB, SE, TTYPE

# The script must not be executed simultaneously
lock = FileLock("/tmp/jasmin_discover")

parser = argparse.ArgumentParser(description='Zabbix Jasmin LLD script')
parser.add_argument('--hostname', required=True, help = "Jasmin's hostname (same configured in Zabbix hosts)")
parser.add_argument('-d', required=True, help = "users or smppcs")
args = parser.parse_args()

# Configuration
zabbix_host = 'monitoring.jookies.net'  # Zabbix Server IP
zabbix_port = 30551                     # Zabbix Server Port
jcli = {'host': args.hostname, # Must be the same configured in Zabbix hosts !
        'port': 8990,
        'username': 'jcliadmin',
        'password': 'jclipwd'}

# Discovery keys
keys = []
keys.append('smppcs')
keys.append('users')


class jCliSessionError(Exception):
    pass

class jCliKeyError(Exception):
    pass

def process_option(tsocket, command, option):
    if command == DO and option == TTYPE:
        tsocket.sendall(IAC + WILL + TTYPE)
        #print 'Sending terminal type "mypython"'
        tsocket.sendall(IAC + SB + TTYPE + '\0' + 'mypython' + IAC + SE)
    elif command in (DO, DONT):
        #print 'Will not', ord(option)
        tsocket.sendall(IAC + WONT + option)
    elif command in (WILL, WONT):
        #print 'Do not', ord(option)
        tsocket.sendall(IAC + DONT + option)

def wait_for_prompt(tn, command = None, prompt = r'jcli :', to = 12):
    """Will send 'command' (if set) and wait for prompt

    Will raise an exception if 'prompt' is not obtained after 'to' seconds
    """

    if command is not None:
        tn.write(command)

    idx, obj, response = tn.expect([prompt], to)
    if idx == -1:
        if command is None:
            raise jCliSessionError('Did not get prompt (%s)' % prompt)
        else:
            raise jCliSessionError('Did not get prompt (%s) for command (%s)' % (prompt, command))
    else:
        return response

def get_list_ids(response):
    "Parse response and get list IDs, otherwise raise a jCliKeyError"
    p = r"^#([A-Za-z0-9_-]+)\s+"
    matches = re.findall(p, response, re.MULTILINE)
    ids = []
    if len(matches) == 0:
        raise jCliKeyError('Cannot extract ids from response %s' % response)
    
    for o in matches:
        if o not in ['Connector', 'User']:
            ids.append(o)
    
    return ids

def main():
    tn = None
    outcome = None
    try:
        # Ensure there are no paralell runs of this script
        lock.acquire(timeout=5)

        # Connect and authenticate
        tn = Telnet(jcli['host'], jcli['port'])
        tn.set_option_negotiation_callback(process_option)
        
        # for telnet session debug:
        #tn.set_debuglevel(1000)
        
        tn.read_until('Authentication required', 8)
        tn.write("\n")
        tn.read_until("Username:", 5)
        tn.write(jcli['username']+"\n")
        tn.read_until("Password:", 5)
        tn.write(jcli['password']+"\n")

        # We must be connected
        idx, obj, response = tn.expect([r'Welcome to Jasmin (\d+\.\d+[a-z]+\d+) console'], 5)
        if idx == -1:
            raise jCliSessionError('Authentication failure')
        
        # Wait for prompt
        wait_for_prompt(tn)

        # Build outcome for requested key
        if args.d == 'smppcs':
            response = wait_for_prompt(tn, command = "stats --smppcs\n")
            smppcs = get_list_ids(response)
            outcome = {'data': []}
            for cid in smppcs:
                outcome['data'].append({'{#CID}': cid})
        elif args.d == 'users':
            response = wait_for_prompt(tn, command = "stats --users\n")
            users = get_list_ids(response)
            outcome = {'data': []}
            for uid in users:
                outcome['data'].append({'{#UID}': uid})
    except LockTimeout:
        print 'Lock not acquired, exiting'
    except AlreadyLocked:
        print 'Already locked, exiting'
    except Exception, e:
        print type(e)
        print 'Error: %s' % e
    finally:
        if tn is not None and tn.get_socket():
            tn.close()
        if outcome is not None:
            print outcome

        # Release the lock
        if lock.i_am_locking():
            lock.release()

if __name__ == '__main__':
    main()