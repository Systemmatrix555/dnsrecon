#!/usr/bin/python
# -*- coding: utf-8 -*-

#    DNSRecon
# TODO:
# 1. Implement whois query of all records, do uniq and perform reverse look up on them.
# 2. Implement saving to file results.
# 3. Finish zone transfer parsing.
# 4. Implement TLD bruteforce.

#    Copyright (C) 2010  Carkis Perez
#
#    This program is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; Applies version 2 of the License.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program; if not, write to the Free Software
#    Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA

__version__ = '0.1'
__author__ = 'Carlos Perez, Carlos_Perez@darkoperator.com'

__doc__ = """
DNSRecon http://www.darkoperator.com

 by Carlos Perez, Darkoperator
for Python 2.7

requires bonjour for Mac, Windows, Linux
requieres pybonjour http://code.google.com/p/pybonjour/
requieres dnspython http://www.dnspython.org/
requieres netaddr https://github.com/drkjam/netaddr/

"""
import time
import Queue
import dns.message
import dns.query
import dns.rdatatype
import dns.resolver
import dns.reversename
import dns.zone
import getopt
import sys
import os
import pybonjour
import select
import string
import socket
import re
import urllib
from netaddr import *
from Queue import Queue
from random import Random
from threading import Thread
from threading import Lock
from time import sleep



# Global Variables for Bruteforce Threads

brtdata = []
lck = Lock()


# Function Definitions
# -------------------------------------------------------------------------------

# Worker & Threadpool classes ripped from
# http://code.activestate.com/recipes/577187-python-thread-pool/


class Worker(Thread):

    """Thread executing tasks from a given tasks queue"""

    def __init__(self, tasks):
        Thread.__init__(self)
        self.tasks = tasks
        self.daemon = True
        self.start()
        # Global variable that will hold the results
        global brtdata
    def run(self):
        found_recrd = []
        while True:
            (func, args, kargs) = self.tasks.get()
            try:
                found_recrd = func(*args, **kargs)
                if found_recrd:
                    lck.acquire()
                    brtdata.append(found_recrd)
                    lck.release()

            except Exception, e:
                print e
            self.tasks.task_done()


class ThreadPool:

    """Pool of threads consuming tasks from a queue"""

    def __init__(self, num_threads):
        self.tasks = Queue(num_threads)
        for _ in range(num_threads):
            Worker(self.tasks)

    def add_task(
        self,
        func,
        *args,
        **kargs
        ):
        """Add a task to the queue"""

        self.tasks.put((func, args, kargs))

    def wait_completion(self):
        """Wait for completion of all the tasks in the queue"""

        self.tasks.join()

class AppURLopener(urllib.FancyURLopener):

    version = 'Mozilla/5.0 (compatible; Googlebot/2.1; + http://www.google.com/bot.html)'
def unique(seq, idfun=repr):
    """
    Function to remove duplicates in an array. Retuns array with duplicates
    removed.
    """
    seen = {}
    return [seen.setdefault(idfun(e),e) for e in seq if idfun(e) not in seen]


def get_whois(ip_addrs):
    """
    Function that returns what whois server is the one to be queried for
    registration information, returns whois.arin.net is not in database, returns
    None if private.
    """
    whois_server = None
    ip = IPAddress(ip_addrs)
    info_of_ip = ip.info
    if ip.version == 4 and ip.is_private() == False:
        for i in info_of_ip['IPv4']:
            whois_server = i['whois']
            if len(whois_server) == 0 and i['status'] != "Reserved":
                whois_server = "whois.arin.net"
            elif len(whois_server) == 0:
                whois_server = None

    return whois_server


def whois(target,whois_srv):
    """
    Performs a whois query againsta arin.net for a given IP, Domain or Host as a
    string and returns the answer of the query.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect((whois_srv, 43))
    s.send(target + "\r\n")
    response = ''
    while True:
        d = s.recv(4096)
        response += d
        if d == '':
            break
    s.close()
    return response


def get_whois_nets(data):
    """
    Parses whois data and extracs the Network Ranges returning an array of lists
    where each list has the starting and ending IP of the found range.
    """
    patern = '([0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}) - ([0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3})'
    results = re.findall(patern,data)
    return results


def expand_cidr(cidr_to_expand):
    """
    Function to expand a given CIDR and return an Array of IP Addresses that
    form the range covered by the CIDR.
    """
    ip_list = []
    c1 = IPNetwork(cidr_to_expand)
    for x in ([str(c) for c in c1.iter_hosts()]):
        ip_list.append(str(x))
    return ip_list


def expand_range(startip,endip):
    """
    Function to expand a given range and return an Array of IP Addresses that
    form the range.
    """
    ip_list = []
    ipr = iter_iprange(startip,endip)
    for i in ipr:
        ip_list.append(str(i))
    return ip_list


def write_to_file(data,target_file):
    """
    Function for writing returned data to a file
    """
    f = open(target_file, "a")
    f.write(data)
    f.close


def zone_transfer(dmain_trg):
    """
    Function for testing for zone transfers for a given Domain, it will parse the
    output by record type.
    """

    zone_success = None
    print '[*] Checking for Zone Transfer for', dmain_trg, \
        'name servers'
    ns_srvs = get_ns(dmain_trg)
    for ns in ns_srvs:
        ns_srv = ''.join(ns[2])
        print '[*] Trying NS server', ns_srv
        try:
            zone = dns.zone.from_xfr(dns.query.xfr(ns_srv, dmain_trg))
            print '[*] Zone Transfer was successful!!'
            for (name, rdataset) in \
                zone.iterate_rdatasets(dns.rdatatype.SOA):
                for rdata in rdataset:
                    print '[*]', '\tSOA', rdata.mname.to_text()

            for (name, rdataset) in \
                zone.iterate_rdatasets(dns.rdatatype.NS):
                for rdata in rdataset:
                    print '[*]', '\tNS', rdata.target.to_text()

            for (name, rdataset) in \
                zone.iterate_rdatasets(dns.rdatatype.TXT):
                for rdata in rdataset:
                    print '[*]', '\tTXT', ''.join(rdata.strings)

            for (name, rdataset) in \
                zone.iterate_rdatasets(dns.rdatatype.SPF):
                for rdata in rdataset:
                    print '[*]', '\tSPF', ''.join(rdata.strings)

            for (name, rdataset) in \
                zone.iterate_rdatasets(dns.rdatatype.MX):
                for rdata in rdataset:
                    print '[*]', '\tMX', str(name) + '.' + dmain_trg, \
                        rdata.exchange.to_text()

            for (name, rdataset) in \
                zone.iterate_rdatasets(dns.rdatatype.AAAA):
                for rdata in rdataset:
                    print '[*]', '\tAAAA', str(name) + '.' + dmain_trg, \
                        rdata.address

            for (name, rdataset) in \
                zone.iterate_rdatasets(dns.rdatatype.A):
                for rdata in rdataset:
                    print '[*]', '\tA', str(name) + '.' + dmain_trg, \
                        rdata.address

            for (name, rdataset) in \
                zone.iterate_rdatasets(dns.rdatatype.CNAME):
                for rdata in rdataset:
                    print '[*]', '\tCNAME', str(name) + '.'\
                         + dmain_trg, rdata.target.to_text()

            for (name, rdataset) in \
                zone.iterate_rdatasets(dns.rdatatype.SRV):
                for rdata in rdataset:
                    print '[*]\t', 'SRV', str(name)+ '.' + dmain_trg, rdata.target, \
                    str(rdata.port), str(rdata.weight)

            for (name, rdataset) in \
                zone.iterate_rdatasets(dns.rdatatype.HINFO):
                for rdata in rdataset:
                    print '[*]', '\tHINFO', str(name) + '.' + dmain_trg, \
                    rdata.cpu, rdata.os

#
#            for (name, rdataset) in \
#                zone.iterate_rdatasets(dns.rdatatype.WKS):
#                for rdata in rdataset:
#                    print '[*]', '\tWKS', str(name) + '.' + dmain_trg
#
#            for (name, rdataset) in \
#                zone.iterate_rdatasets(dns.rdatatype.RP):
#                for rdata in rdataset:
#                    print '[*]', '\tRP', str(name) + '.' + dmain_trg
#
#            for (name, rdataset) in \
#                zone.iterate_rdatasets(dns.rdatatype.AFSDB):
#                for rdata in rdataset:
#                    print '[*]', '\tAFSDB', str(name) + '.' + dmain_trg
#
#            for (name, rdataset) in \
#                zone.iterate_rdatasets(dns.rdatatype.X25):
#                for rdata in rdataset:
#                    print '[*]', '\tX25', str(name) + '.' + dmain_trg
#
#            for (name, rdataset) in \
#                zone.iterate_rdatasets(dns.rdatatype.ISDN):
#                for rdata in rdataset:
#                    print '[*]', '\tISDN', str(name) + '.' + dmain_trg
#
#            for (name, rdataset) in \
#                zone.iterate_rdatasets(dns.rdatatype.RT):
#                for rdata in rdataset:
#                    print '[*]', '\tRT', str(name) + '.' + dmain_trg
#
#            for (name, rdataset) in \
#                zone.iterate_rdatasets(dns.rdatatype.NSAP):
#                for rdata in rdataset:
#                    print '[*]', '\tNSAP', str(name) + '.' + dmain_trg
#
#            for (name, rdataset) in \
#                zone.iterate_rdatasets(dns.rdatatype.NSAP_PTR):
#                for rdata in rdataset:
#                    print '[*]', '\tNSAP_PTR', str(name) + '.'\
#                         + dmain_trg
#
#            for (name, rdataset) in \
#                zone.iterate_rdatasets(dns.rdatatype.SIG):
#                for rdata in rdataset:
#                    print '[*]', '\tSIG', str(name) + '.' + dmain_trg
            zone_success = True
        except:
            print '[-] Zone Transfer Failed!'
    return zone_success


def get_cname(host_trg):
    """
    Function for CNAME Record resolving. Retuns the hostnames for a given alias.
    Returns array with value.
    """
    host_name = []
    names_answers = res.query(host_trg, 'CNAME')
    for crdata in names_answers:
        host_name.append(crdata.target.to_text())
    return host_name


def get_a(host_trg):
    """
    Function for resolving the A Record for a given host. Returns an Array of
    the IP Address it resolves to.
    """
    address = []
    try:
        ipv4_answers = res.query(host_trg, 'A')
        for ardata in ipv4_answers:
            address.append(ardata.address)
            return address
    except:
        return address


def get_aaaa(host_trg):
    """
    Function for resolving the AAAA Record for a given host. Returns an Array of
    the IP Address it resolves to.
    """
    address = []
    try:
        ipv6_answers = res.query(host_trg, 'AAAA')
        for ardata in ipv6_answers:
            address.append(ardata.address)
            return address
    except:
        return address


def get_mx(domain):
    """
    Function for MX Record resolving. Returns all MX records. Retuns also the IP
    address of the host both in IPv4 and IPv6. Returns an Array
    """
    mx_records = []
    answers = res.query(domain, 'MX')
    for rdata in answers:
        try:
            name = rdata.exchange.to_text()
            ipv4_answers = res.query(name, 'A')
            for ardata in ipv4_answers:
                mx_records.append(['MX', name[:-1], ardata.address,
                                rdata.preference])
        except:
            pass
    try:
        for rdata in answers:
            name = rdata.exchange.to_text()
            ipv6_answers = res.query(name, 'AAAA')
            for ardata in ipv6_answers:
                mx_records.append(['MX', name[:-1], ardata.address,
                                  rdata.preference])
        return mx_records
    except:
        return mx_records


def get_ns(domain):
    """
    Function for NS Record resolving. Returns all NS records. Retuns also the IP
    address of the host both in IPv4 and IPv6. Returns an Array.
    """
    ns_srvs = []
    answers = res.query(domain, 'NS')
    for rdata in answers:
        name = rdata.target.to_text()
        ipv4_answers = res.query(name, 'A')
        for ardata in ipv4_answers:
            ns_srvs.append(['NS', name[:-1], ardata.address])
    try:
        for rdata in answers:
            name = rdata.target.to_text()
            ipv6_answers = res.query(name, 'AAAA')
            for ardata in ipv6_answers:
                ns_srvs.append(['NS', name[:-1], ardata.address])
        return ns_srvs
    except:
        return ns_srvs


def get_soa(domain):
    """
    Function for SOA Record resolving. Returns all SOA records. Retuns also the IP
    address of the host both in IPv4 and IPv6. Returns an Array.
    """
    soa_records = []
    answers = res.query(domain, 'SOA')
    for rdata in answers:
        name = rdata.mname.to_text()
        ipv4_answers = res.query(name, 'A')
        for ardata in ipv4_answers:
            soa_records.extend(['SOA', name[:-1], ardata.address])
    try:
        for rdata in answers:
            name = rdata.mname.to_text()
            ipv4_answers = res.query(name, 'AAAA')
            for ardata in ipv4_answers:
                soa_records.extend(['SOA', name[:-1], ardata.address])
        return soa_records
    except:
        return soa_records


def get_spf(domain):
    """
    Function for SPF Record resolving returns the string with the SPF definition.
    Prints the string for the SPF Record and Returns the string
    """
    try:
        answers = res.query(domain, 'SPF')
        for rdata in answers:
            name = rdata.strings
            print '[*]', 'SPF', name
    except:
        return None


def get_txt(domain):
    """
    Function for TXT Record resolving returns the string.
    """
    try:
        answers = res.query(domain, 'TXT')
        for rdata in answers:
            name = rdata.strings
            print '[*]\t', 'TXT', name
    except:
        return None


def check_wildcard(domain_trg):
    """
    Function for checking if Wilcard resolution is configured for a Domain
    """
    wildcard = None
    test_name = ''.join(Random().sample(string.letters + string.digits,
                        12)) + '.' + domain_trg
    ips = get_a(test_name)
    if len(ips) > 0:
        print '[-] Wildard resolution is enabled on this domain'
        print '[-] It is resolving to', ''.join(ips)
        print '[-] All queries will resolv to this address!!'
        wildcard = ''.join(ips)
    return wildcard


def get_ptr(ipaddress):
    """
    Function for resolving PTR Record given it's IPv4 or IPv6 Address.
    """
    found_ptr = []
    n = dns.reversename.from_address(ipaddress)
    try:
        answers = res.query(n, 'PTR')
        for a in answers:
            found_ptr.append(['PTR', a.target.to_text(),ipaddress])
        return found_ptr
    except:
        return None


def get_srv(host):
    """
    Function for resolving SRV Records.
    """
    record = []
    try:
        answers = res.query(host, 'SRV')
        for a in answers:
            target = a.target.to_text()
            for ip in get_a(target):
                record.append(['SRV', host, a.target.to_text(), ip,
                              str(a.port), str(a.weight)])
    except:
        return record
    return record

def brute_tlds(domain):
    # tlds taken from http://data.iana.org/TLD/tlds-alpha-by-domain.txt
    gtld = ['co','com','net','biz','org']
    tlds = ['ac', 'ad', 'aeaero', 'af', 'ag', 'ai', 'al', 'am', 'an', 'ao', 'aq', 'ar',
    'arpa', 'as', 'asia', 'at', 'au', 'aw', 'ax', 'az', 'ba', 'bb', 'bd', 'be', 'bf', 'bg',
    'bh', 'bi', 'biz', 'bj', 'bm', 'bn', 'bo', 'br', 'bs', 'bt', 'bv', 'bw', 'by', 'bzca',
    'cat', 'cc', 'cd', 'cf', 'cg', 'ch', 'ci', 'ck', 'cl', 'cm', 'cn', 'co', 'com', 'coop',
    'cr', 'cu', 'cv', 'cx', 'cy', 'cz', 'de', 'dj', 'dk', 'dm', 'do', 'dz', 'ec', 'edu', 'ee',
    'eg', 'er', 'es', 'et', 'eu', 'fi', 'fj', 'fk', 'fm', 'fo', 'fr', 'ga', 'gb', 'gd', 'ge',
    'gf', 'gg', 'gh', 'gi', 'gl', 'gm', 'gn', 'gov', 'gp', 'gq', 'gr', 'gs', 'gt', 'gu', 'gw',
    'gy', 'hk', 'hm', 'hn', 'hr', 'ht', 'hu', 'id', 'ie', 'il', 'im', 'in', 'info', 'int',
    'io', 'iq', 'ir', 'is', 'it', 'je', 'jm', 'jo', 'jobs', 'jp', 'ke', 'kg', 'kh', 'ki', 'km',
    'kn', 'kp', 'kr', 'kw', 'ky', 'kz', 'la', 'lb', 'lc', 'li', 'lk', 'lr', 'ls', 'lt', 'lu',
    'lv', 'ly', 'ma', 'mc', 'md', 'me', 'mg', 'mh', 'mil', 'mk', 'ml', 'mm', 'mn', 'mo',
    'mobi', 'mp', 'mq', 'mr', 'ms', 'mt', 'mu', 'museum', 'mv', 'mw', 'mx', 'my', 'mz', 'na',
    'name', 'nc', 'ne', 'net', 'nf', 'ng', 'ni', 'nl', 'no', 'np', 'nr', 'nu', 'nz', 'om',
    'org', 'pa', 'pe', 'pf', 'pg', 'ph', 'pk', 'pl', 'pm', 'pn', 'pr', 'pro', 'ps', 'pt', 'pw',
    'py', 'qa', 're', 'ro', 'rs', 'ru', 'rw', 'sa', 'sb', 'sc', 'sd', 'se', 'sg', 'sh', 'si',
    'sj', 'sk', 'sl', 'sm', 'sn', 'so', 'sr', 'st', 'su', 'sv', 'sy', 'sz', 'tc', 'td', 'tel',
    'tf', 'tg', 'th', 'tj', 'tk', 'tl', 'tm', 'tn', 'to', 'tp', 'tr', 'travel', 'tt', 'tv',
    'tw', 'tz', 'ua', 'ug', 'uk', 'us', 'uy', 'uz', 'va', 'vc', 've', 'vg', 'vi', 'vn', 'vu',
    'wf', 'ws', 'ye', 'yt', 'za', 'zm', 'zw']
 
    domain_main = domain.split(".")[0]
    for t in tlds:
        pool.add_task(get_ip, domain_main + "." + t)
        for g in gtld:
            pool.add_task(get_ip, domain_main+ "." + g + "." + t)
    # Wait for threads to finish.
    pool.wait_completion()
    # Process the output of the threads.
    for rcd_found in brtdata:
        for rcd in rcd_found:
            print "[*]\t"," ".join(rcd)

def brute_srv(domain):
    """
    Bruteforce most common SRV records for a given Domain. Returns an Array with
    records found.
    """
    srv = []
    srvrcd = [
        '_gc._tcp.',
        '_kerberos._tcp.',
        '_kerberos._udp.',
        '_ldap._tcp',
        '_test._tcp.',
        '_sips._tcp.',
        '_sip._udp.',
        '_sip._tcp.',
        '_aix._tcp.',
        '_aix._tcp.',
        '_finger._tcp.',
        '_ftp._tcp.',
        '_http._tcp.',
        '_nntp._tcp.',
        '_telnet._tcp.',
        '_whois._tcp.',
        '_h323cs._tcp.',
        '_h323cs._udp.',
        '_h323be._tcp.',
        '_h323be._udp.',
        '_h323ls._tcp.',
        '_h323ls._udp.',
        '_sipinternal._tcp.',
        '_sipinternaltls._tcp.',
        '_sip._tls.',
        '_sipfederationtls._tcp.',
        '_jabber._tcp.',
        '_xmpp-server._tcp.',
        '_xmpp-client._tcp.',
        '_imap.tcp.',
        '_certificates._tcp.',
        '_crls._tcp.',
        '_pgpkeys._tcp.',
        '_pgprevokations._tcp.',
        '_cmp._tcp.',
        '_svcp._tcp.',
        '_crl._tcp.',
        '_ocsp._tcp.',
        '_PKIXREP._tcp.',
        '_smtp._tcp.',
        '_hkp._tcp.',
        '_hkps._tcp.',
        '_jabber._udp.',
        '_xmpp-server._udp.',
        '_xmpp-client._udp.',
        '_jabber-client._tcp.',
        '_jabber-client._udp.',
        ]

    for srvtype in srvrcd:
        pool.add_task(get_srv, srvtype + domain)
    # Wait for threads to finish.
    pool.wait_completion()
    # Make sure we clear the variable
    for rcd_found in brtdata:
        for rcd in rcd_found:
            srv.append(rcd)
            print "[*]\t", " ".join(rcd)
    return srv


def brute_reverse(ip_list):
    """
    Reverse lookup brite force for given CIDR example 192.168.1.1/24. Returns an
    Array of found records.
    """
    # Resolv each IP in a separte thread.
    for x in ip_list:
        pool.add_task(get_ptr, x)
    # Wait for threads to finish.
    pool.wait_completion()
    for rcd_found in brtdata:
        for rcd in rcd_found:
            print "[*]\t"," ".join(rcd)


def get_ip(hostname):
    """
    Function resolves a host name to its given A and/or AAA record. Returns Array
    of found hosts and IPv4 or IPv6 Address.
    """
    found_ip_add = []
    ipv4 = get_a(hostname)
    time.sleep(0.2)
    if ipv4:
        for ip in ipv4:
            found_ip_add.append(["A",hostname,ip])
    ipv6 = get_aaaa(hostname)
    if ipv6:
        for ip in ipv6:
            found_ip_add.append(["AAAA",hostname,ip])
    return found_ip_add


def brute_domain(dict, dom):
    """
    Main Function for domain brute forcing
    """
    continue_brt = 'y'
    global brtdata
    # Check if wildcard resolution is enabled

    if check_wildcard(dom):
        continue_brt = raw_input('[*] Do you wish to continue? y/n ')
    if continue_brt == 'y':

        # Check if Dictionary file exists

        if os.path.isfile(dict):
            f = open(dict, 'r+')

            # Thread bruteforce.

            for line in f:
                target = line.strip() + '.' + dom.strip()
                pool.add_task(get_ip, target)
        # Wait for threads to finish
        pool.wait_completion()
        # Process the output of the threads.
        for rcd_found in brtdata:
            for rcd in rcd_found:
                print "[*]\t"," ".join(rcd)


def in_cache(zone, rdata_type, ns):
    """
    Function for Cache Snooping, it will check a given NS server for specific
    type of records for a given domain are in it's cache. Returns an Array with
    records found, their type and NS server that was tested.
    """
    found_in_cache = []
    if rdata_type == 'NS':
        qtype = dns.rdatatype.NS
    elif rdata_type == 'MX':
        qtype = dns.rdatatype.MX
    elif rdata_type == 'A':
        qtype = dns.rdatatype.A
    elif rdata_type == 'CNAME':
        qtype = dns.rdatatype.CNAME
    elif rdata_type == 'SOA':
        qtype = dns.rdatatype.SOA
    elif rdata_type == 'SOA':
        qtype = dns.rdatatype.PRT
    elif rdata_type == 'SOA':
        qtype = dns.rdatatype.AAA
    elif rdata_type == None:
        qtype = dns.rdatatype.A
    query = dns.message.make_query(zone, qtype, dns.rdataclass.IN)
    query.flags ^= dns.flags.RD
    answer = dns.query.udp(query, ns)
    if len(answer.answer) > 0:
        print '[*]', zone, 'Present in cache'
        found_in_cache.append([qtype,zone,ns])
    return found_in_cache


def snoop_cache(ns,in_cache,dict):
    """
    Function to check each domain name in a given file and record type against a
    target NS Server to verify if an entry exists in it's cache.
    """
     # Check if Dictionary file exists

    if os.path.isfile(dict):
        f = open(dict, 'r+')
        for line in f:
            in_cache(line,in_cache,ns)

def mdns_browse(regtype):
    """
    Function for resolving a specific mDNS record in the Local Subnet.
    """
    found_mdns_records = []
    domain = None
    browse_timeout = 2
    resolve_timeout = 2
    results = []
    resolved = []

    def resolve_callback(
        sdRef,
        flags,
        interfaceIndex,
        errorCode,
        fullname,
        hosttarget,
        port,
        txtRecord,
        ):
        if errorCode == pybonjour.kDNSServiceErr_NoError:
            results.append({
                'name': fullname,
                'host': hosttarget.strip(),
                'port': port,
                'txtRecord': txtRecord.strip(),
                })
            resolved.append(True)

    def browse_callback(
        sdRef,
        flags,
        interfaceIndex,
        errorCode,
        serviceName,
        regtype,
        replyDomain,
        ):
        if errorCode != pybonjour.kDNSServiceErr_NoError:
            return

        if not flags & pybonjour.kDNSServiceFlagsAdd:

            # Service removed

            return

        resolve_sdRef = pybonjour.DNSServiceResolve(
            0,
            interfaceIndex,
            serviceName,
            regtype,
            replyDomain,
            resolve_callback,
            )

        try:
            while not resolved:
                ready = select.select([resolve_sdRef], [], [],
                        resolve_timeout)

                if resolve_sdRef not in ready[0]:

                    # Resolve timed out

                    break

                pybonjour.DNSServiceProcessResult(resolve_sdRef)
            else:

                resolved.pop()
        finally:

            resolve_sdRef.close()

    browse_sdRef = pybonjour.DNSServiceBrowse(regtype=regtype,
            domain=domain, callBack=browse_callback)

    try:
        while True:
            ready = select.select([browse_sdRef], [], [],
                                  browse_timeout)

            if not ready[0]:
                break

            if browse_sdRef in ready[0]:
                pybonjour.DNSServiceProcessResult(browse_sdRef)

            _results = results

            for result in _results:
                found_mdns_records = [result]
    finally:

        browse_sdRef.close()
    return found_mdns_records


def mdns_enum():
    """
    Function for enumerating several know types of mDNS records in the local
    subnet.
    """

    mdns_types = [
        '_appletv-itunes._tcp',
        '_touch-able._tcp',
        '_sleep-proxy._tcp',
        '_raop._tcp',
        '_touch-remote._tcp',
        '_appletv-pair._tcp',
        '_appletv._tcp',
        '_rfb._tcp',
        '_adisk._tcp',
        '_daap._tcp',
        '_presence._tcp',
        '_ichat._tcp',
        '_http._tcp',
        '_ftp._tcp',
        '_rtsp._tcp',
        '_distcc._tcp',
        '_tivo_servemedia._tcp',
        '_airport._tcp',
        '_afpovertcp._tcp',
        '_printer._tcp',
        '_ipp._tcp',
        '_pdl-datastream._tcp',
        '_eppc._tcp',
        '_workstation._tcp',
        '_ssh._tcp',
        '_telnet._tcp',
        '_tftp._udp',
        '_smb._tcp',
        '_netbios-ns._udp',
        '_netbios-ssn._tcp',
        '_apple-sasl._tcp',
        '_ssscreenshare._tcp',
        '_postgresql._tcp',
        '_pop3._tcp',
        '_imaps._tcp',
        '_imap._tcp',
        '_pop3s._tcp',
        '_bootps._udp',
        '_shell._tcp',
        '_login._tcp',
        '_teleport._udp',
        '_dacp._tcp',
        '_dpap._tcp',
        '_auth._tcp',
        '_fmpro-internal._tcp',
        '_h323._tcp',
        '_iwork._tcp',
        '_nfs._tcp',
        '_ptp._tcp',
        '_spl-itunes._tcp',
        '_spr-itunes._tcp',
        '_upnp._tcp',
        '_webdav._tcp',
        '_ws._tcp',
        '_exec._tcp',
        '_net-assistant._udp',
        '_raop._tcp',
        '_servermgr._tcp',
        '_sftp-ssh._tcp',
        '_asr._tcp',
        '_dacp._tcp',
        '_domain._udp',
        '_dns-llq._udp',
        '_iax._udp',
        '_kerberos-adm._tcp',
        '_kerberos._tcp',
        '_ntp._tcp',
        '_rsync._tcp',
        '_sip._udp',
        '_xmpp-client._tcp',
        '_xmpp-server._tcp',
        '_skype._tcp',
        '_ica-networking._tcp',
        '_presence._tcp',
        '_ofocus-sync._tcp',
        '_zuul1000205._udp',
        '_sub._ipp._tcp'
        ]
    for m in mdns_types:
        pool.add_task(mdns_browse, m)
    pool.wait_completion()
    for i in brtdata:
        for e in i:
            print "[*]\tHost:",e['host']
            print "[*]\tName:",e['name'].encode("utf-8")
            print "[*]\tPort:",e['port']
            print "[*]\tTXTRecord:",e['txtRecord'].replace("\n"," ")
            print "[*]"


def scrape_google(dom):
    """
    Function for enumerating subdomains and hosts by scrapping google.
    """
    results = []
    filtered = []
    searches = ["100", "200","300","400","500"]
    data = ""
    urllib._urlopener = AppURLopener()
    #opener.addheaders = [('User-Agent','Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)')]
    for n in searches:
        url = "http://google.com/search?hl=en&lr=&ie=UTF-8&q=%2B"+dom+"&start="+n+"&sa=N&filter=0&num=100"
        sock = urllib.urlopen(url)
        data += sock.read()
        sock.close()
    results.extend(unique(re.findall("href=\"htt\w{1,2}:\/\/([^:?]*[a-b0-9]*[^:?]*\."+dom+")\/", data)))
    # Make sure we are only getting the host
    for f in results:
        filtered.extend(re.findall("^([a-z.0-9^]*"+dom+")", f))
    sleep(2)
    return unique(filtered)


def general_enum(domain, do_axfr,do_google):
    """
    Function for performing general enumeration of a domain. It gets SOA, NS, MX
    A, AAA and SRV records for a given domain.It Will first try a Zone Transfer
    if not successfull it will try indivifual record type enumeration. If chosen
    it will also perform a Google Search and scrape the results for hostnames and
    perform an A and AAA query against them.
    """
    check_wildcard(domain)
    if do_axfr is not None:
        zone_transfer(domain)
    found_soa_record = get_soa(domain)
    print '[*]\t', found_soa_record[0], found_soa_record[1], found_soa_record[2]
    for ns_rcrd in get_ns(domain):
        print '[*]\t', ns_rcrd[0], ns_rcrd[1], ns_rcrd[2]
    for mx_rcrd in get_mx(domain):
        print '[*]\t', mx_rcrd[0], mx_rcrd[1], mx_rcrd[2]
    get_spf(domain)
    get_txt(domain)
    get_ip(domain)
    print '[*] Enumerating SRV Records'
    brute_srv(domain)
    if do_google is not None:
        print '[*] Performing Google Search Enumeration'
        for sd in scrape_google(domain):
            for sdip in get_ip(sd):
                print '[*]\t', sdip[0], sdip[1], sdip[2]

def usage():
    print "Usage: dnsrecon.py <options>\n"
    print "Options:"
    print "  -h, --help                  Show this help message and exit"
    print "  -d, --domain      <domain>  Domain to Target for enumeration."
    print "  -c, --cidr        <range>   CIDR for reverse lookup bruteforce (range/bitmask)."
    print "  -r, --range       <range>   IP Range for reverse lookup bruteforce (first-last)."
    print "  -n, --name_server <name>    Domain server to use, if none is given the SOA of the"
    print "                              target will be used"
    #print "  -f, --output_file <file>    File to save found records."
    print "  -D, --dictionary  <file>    Dictionary file of subdomain and hostnames to use for"
    print "                              bruteforce."
    print "  -t, --type        <types>   Specify the type of enumeration to perform:"
    print "                              mdns    To Enumerate local subnet with mDNS.\n"
    print "                              std     To Enumerate general record types, enumerates."
    print "                                      SOA, NS, A, AAAA, MX and SRV if AXRF on the"
    print "                                      NS Servers fail.\n"
    print "                              rvl     To Reverse Look Up a given CIDR IP range.\n"
    print "                              brt     To Bruteforce Domains and Hosts using a given"
    print "                                      dictionary.\n"
    print "                              srv     To Enumerate common SRV Records for a given \n"
    print "                                      domain.\n"
    print "                              axfr    Test all NS Servers in a domain for misconfigured\n"
    print "                                      zone transfers.\n"
    print "                              snoop   To Perform a Cache Snooping against al NS "
    print "                                      servers for a given domain, testing all with"
    print "                                      file containing the domains and a given Record"
    print "                                      Type.\n"
    print "                              tld     Will remove the TLD of given domain and test against"
    print "                                      all TLD's registered in IANA\n"
    print "  -x, --axfr                  Perform AXFR with the standard enumeration."
    print "  -g, --google                Perform Google enumeration with the standard enumeration."
    #print "  -w, --do_whois              Do deep whois record analisys and reverse lookup of IP"
    #print "                              ranges found thru whois when doing standard query."
    print "  -T, --cache_type  <type>    Type of record to perform Cache Snooping on, Dictionary"
    print "                              and NS Server. File with hosts or domain is given with"
    print "                              -D option\n"
    print "  --threads          <number> Number of threads to use in Range Reverse Lookup, Fordward"
    print "                              Lookup Bruteforce and SRV Record Enumeration"
    print "  --lifetime         <number> Time to wait for a server to response to a query."
    exit(0)


# Main
#-------------------------------------------------------------------------------

# Option Variables
domain = None
cidr = None
ns_server = None
output_file = None
dict = None
type = None
xfr = None
goo = None
cache_type = None
deep_whois = None
thread_num = 10
request_timeout = 1.0
ip_list = []
ip_range = None
ip_range_pattern = '([0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3})-([0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3})'

# Define options
options, remainder = getopt.getopt(sys.argv[1:], 'hd:c:n:f:D:t:xT:gwr:',
                                   ['help',
                                   'domain=',
                                   'cidr=',
                                   'name_server=',
                                   'output_file=',
                                   'dictionary=',
                                   'type=',
                                   'axfr',
                                   'cache_type=',
                                   'google',
                                   'do_whois',
                                   'range=',
                                   'lifetime=',
                                   'threads='])
for opt, arg in options:
    if opt in ('-t','--type'):
        type = arg
    elif opt in ('-d','--domain'):
        domain = arg
    elif opt in ('-c','--cidr'):
        ip_list.extend(expand_cidr(arg))
    elif opt in ('-n','--name_server'):
        ns_server = arg
    elif opt in ('-f','--output_file'):
        output_file = arg
    elif opt in ('-D','--dictionary'):
        dict = arg
    elif opt in ('-x','--axfr'):
        xfr = True
    elif opt in ('-T','--cache_type'):
        type = arg
    elif opt in ('-g','--google'):
        goo = True
    elif opt in ('-w','--do_whois'):
        deep_whois = True
    elif opt in ('-r','--range'):
        ip_range = re.findall(ip_range_pattern,arg)
        ip_list.extend(expand_range(ip_range[0][0],ip_range[0][1]))
    elif opt in ('--theads'):
        thread_num = int(arg)
    elif opt in ('--lifetime'):
        request_timeout = float(arg)
    elif opt in ('-h'):
        usage()
# Setting the number of threads to 10
pool = ThreadPool(thread_num)
if type is not None:
    # We use system DNS for 1st query for SOA Record
    if ns_server:
        print "[*] Changing to server: ", ns_server
        res = dns.resolver.Resolver(configure=False)
        res.nameservers = [ns_server]
    else:
        res = dns.resolver.Resolver(configure=True)
    # Set timing
    res.timeout = request_timeout
    res.lifetime = request_timeout
    for r in type.split(','):
        try:
            if r == 'axfr':
                print '[*] Testing NS Servers for Zone Transfer'
                zone_transfer(domain)
            elif r == 'std':
                print "[*] Performing General Enumeration of Domain:",domain
                general_enum(domain, xfr, goo)
            elif r == 'rvl':
                if len(ip_list) > 0:
                    print '[*] Reverse Lookup of a Range'
                    brute_reverse(ip_list)
                else:
                    print '[-] Failed CIDR or Range is Required for type rvl'
            elif r == 'brt':
                if dict is not None:
                    print '[*] Performing host and subdomain bruteforce against', \
                        domain
                    brute_domain(dict, domain)
                else:
                    print '[-] No Dictionary file specified!'
            elif r == 'srv':
                print '[*] Enumerating Common SRV Records against', \
                    domain
                brute_srv(domain)
            elif r == 'mdns':
                print '[*] Enumerating most common mDNS Resords on Subnet'
                mdns_enum()
            elif r == 'tld':
                print "[*] Performing TLD Bruteforce Enumeration against", domain
                brute_tlds(domain)
            elif r == "snoop":
                print "[*] Performing Cache Snooping against NS Server:", ns_server
            else:
                print "[-] This type of scan is not in the list", r
                usage()
        except dns.resolver.NXDOMAIN:
            print "[-] Could not resolve domain:",domain
        except dns.exception.Timeout:
            print "[-] A timeout error occured please make sure you can reach the target DNS Servers"
            print "[-] directly and requests are not being filtered. Increese the timeout from 1.0 second"
            print "[-] to a higher number with --lifetime <time> option."
else:
    usage()