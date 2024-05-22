#!/usr/bin/env python

"""
Copyright (c) 2024 INFIGO IS d.o.o. (https://www.infigo.is)
Built by Fran Cutura (fran.cutura@infigo.is), Bojan Zdrnja (bojan.zdrnja@infigo.is)
"""

import asyncio
import argparse
import warnings
import ipaddress
import logging
import re
import csv
import db
import os.path
import sys


from tqdm.asyncio import tqdm_asyncio
from aioquic.asyncio import connect
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.logger import QuicLogger
from aioquic.quic.configuration import QuicConfiguration
from cryptography.utils import CryptographyDeprecationWarning

warnings.filterwarnings(action="ignore", category=CryptographyDeprecationWarning)

TIMEOUT = 5
CONCURRENCY = 50

PROTOCOL_LIST = {
    "http/0.9": "HTTP/0.9",
    "http/1.0": "HTTP/1.0",
    "http/1.1": "HTTP/1.1",
    "spdy/1": "SPDY/1",
    "spdy/2": "SPDY/2",
    "spdy/3": "SPDY/3",
    "stun.turn": "Traversal Using Relays around NAT",
    "stun.nat-discovery": "NAT discovery using Session Traversal Utilities for NAT",
    "h2": "HTTP/2 over TLS",
    "h2c": "HTTP/2 over TCP",
    "webrtc": "WebRTC Media and Data",
    "c-webrtc": "Confidential WebRTC Media and Data",
    "ftp": "FTP",
    "imap": "IMAP",
    "pop3": "POP3",
    "managesieve": "ManageSieve",
    "coap": "CoAP",
    "xmpp-client": "XMPP jabber:client namespace",
    "xmpp-server": "XMPP jabber:server namespace",
    "acme-tls/1": "acme-tls/1",
    "mqtt": "OASIS Message Queuing Telemetry Transport ",
    "dot": "DNS-over-TLS",
    "ntske/1": "Network Time Security Key Establishment, version 1",
    "sunrpc": "SunRPC",
    "h3": "HTTP/3",
    "smb": "SMB2",
    "irc": "IRC",
    "nntp": "NNTP",
    "nnsp": "NNTP",
    "doq": "DoQ",
    "sip/2": "SIP",
    "tds/8.0": "TDS/8.0",
    "dicom": "DICOM 	",
    "h3-NN": "HTTP/3 over QUIC I-D draft",
    "h3-T0NN": "Google variant of HTTP/3 over QUIC",
    "h3-Q0NN": "Google variant of HTTP/3 over QUIC",
    "http/2+quic": "Google variant of HTTP/3 over QUIC",
    "http/2+quic/NN": "Google variant of HTTP/3 over QUIC",
    "quic": "Google variant of HTTP/3 over QUIC",
    "h3-fb-NN": "Facebook variant of HTTP/3 over QUIC I-D draft",
    "hq-NN": "HTTP/0.9 over QUIC I-D draft, used for interoperability testing",
    "hq": "HTTP/0.9 over QUIC v1, used for interoperability testing",
    "hq-interop": "HTTP/0.9 over QUIC v1, used for interoperability testing",
    "perf": "Performance testing protocol over QUIC",
    "siduck": "Simple DATAGRAM test over QUIC",
    "siduck-NN": "Simple DATAGRAM test over QUIC",
    "wq-vvv-NN": "WebTransport QuicTransport",
    "doq-iNN": "DNS over QUIC",
    "qrt-NN": "QRT: QUIC RTP Tunnelling",
    "libp2p": "libp2p",
}


def parse_ports(port_spec):
    ports = set()
    port_ranges = port_spec.split(",")
    for port_range in port_ranges:
        if "-" in port_range:
            start, end = map(int, port_range.split("-"))
            ports.update(range(start, end + 1))
        else:
            ports.add(int(port_range))
    return sorted(ports)


def parse_hosts(host_spec):
    hosts = []
    for host_str in host_spec.split(","):
        ip_range_match = re.match(
            r"^(\d+\.\d+\.\d+\.\d+)\s*-\s*(\d+\.\d+\.\d+\.\d+)$", host_str.strip()
        )
        if ip_range_match:
            start_ip = ipaddress.ip_address(ip_range_match.group(1))
            end_ip = ipaddress.ip_address(ip_range_match.group(2))
            ip_range = range(int(start_ip), int(end_ip) + 1)
            hosts.extend(str(ipaddress.ip_address(ip)) for ip in ip_range)
        elif "/" in host_str:
            cidr = ipaddress.ip_network(host_str.strip(), strict=False)
            hosts.extend(str(ip) for ip in cidr)
        else:
            hosts.append(host_str.strip())
    return hosts

def parse_file(file_spec):
    hosts = []
    host_spec = ""

    with open(file_spec, 'r') as f:
        for line in f:
            line = line.strip()
            host_spec = host_spec + ',' + line

    hosts = parse_hosts(host_spec)
    return hosts

def parse_arguments():
    global TIMEOUT, CONCURRENCY

    parser = argparse.ArgumentParser(
        description="quicmap.py - script that does QUIC scanning"
    )
    parser.add_argument(
        "--hosts", help="The target host(s), comma separated hosts or IP range(s)", required=False
    )
    parser.add_argument(
        "-p",
        "--ports",
        metavar="PORTS",
        default="1-1000",
        help="Port range (e.g., '80', '1-1024', '80,443,1000-2000'). Default is '1-1000'",
    )
    parser.add_argument(
        "-t",
        "--timeout",
        type=int,
        default=5,
        help="Timeout for a UDP connection in seconds. Default is 5 seconds.",
    )
    parser.add_argument(
        "-c",
        "--concurrency",
        type=int,
        default=50,
        help="Number of concurrent connections to spawn. Default is 50.",
    )
    parser.add_argument(
        "-f",
        "--file",
        required=False,
        type=str,
        help="File containing target host(s), one host or IP range(s) per line",
    )

    args = parser.parse_args()

    if (args.hosts is None and args.file is None):
        print("quicmap.py: error: the following arguments are conditionally required: hosts or file")
        exit(1)

    host_spec = args.hosts
    port_spec = args.ports
    file_spec = args.file
    TIMEOUT = args.timeout
    CONCURRENCY = args.concurrency

    if (file_spec is None):
        hosts = parse_hosts(host_spec)
    else:
        if os.path.exists(file_spec):
            hosts = parse_file(file_spec)
        else:
            print("quicmap.py: error: the file does not exists")
            exit(1)
        
    ports = parse_ports(port_spec)
    
    logging.info("Hosts: ", hosts)
    logging.info("Ports: ", ports)

    return hosts, ports


def exception_handler(loop, context):
    exception = context["exception"]
    message = context["message"]
    logging.info(f"Task failed, msg={message}, exception={exception}")


def pretty_print(item: dict):
    item["server_versions"] = [hex(ver) for ver in item["server_versions"]]
    item["ALPN"] = [f"{item} ({PROTOCOL_LIST[item]})" for item in item["ALPN"]]
    if not item["ALPN"]:
        item["ALPN"] = "?"

    max_key_length = max(len(key) for key in item.keys())

    for key, value in item.items():
        if key != "success":
            print(
                f"{key.ljust(max_key_length)} : {value if not isinstance(value, list) else ', '.join(value)}"
            )
    print()


async def test_alpn(endpoint: str, port: int, protocols: list) -> dict:
    configuration = QuicConfiguration(
        alpn_protocols=protocols, quic_logger=QuicLogger(), verify_mode=False
    )
    # Forces version negotiation
    configuration.supported_versions.insert(0, 0x1A2B3D4A)
    success = False

    try:
        async with connect(
            endpoint, port, configuration=configuration
        ) as quic_connection:
            await quic_connection.ping()
            success = True
    except Exception:
        pass

    # Find server supported versions
    server_versions = []
    for event in configuration.quic_logger.to_dict()["traces"][0]["events"]:
        if (
            event["name"] == "transport:version_information"
            and event["data"].get("server_versions") is not None
        ):
            server_versions = event["data"].get("server_versions")
        elif (
            event["name"] == "transport:packet_received"
            and len(event["data"].get("frames", [])) > 0
            and event["data"]["frames"][0].get("frame_type") == "connection_close"
        ):
            # Probably application error. Report this ALPN
            if event["data"]["frames"][0].get("error_code") != 376:
                success = True

    return {
        "endpoint": endpoint,
        "port": port,
        "server_versions": server_versions,
        "ALPN": protocols if success else [],
    }


async def quic_map(endpoint: str, port: int, sem: asyncio.Semaphore) -> list:
    async with sem:
        tasks = [
            asyncio.create_task(test_alpn(endpoint, port, list(PROTOCOL_LIST.keys())))
        ]
        done, pending = await asyncio.wait(tasks, timeout=TIMEOUT)

    # Cancel pings that don't respond
    for fut in pending:
        fut.cancel()

    # Brute-force ALPNS
    alpn_tasks = []
    for task in done:
        result = task.result()
        for proto in PROTOCOL_LIST.keys():
            alpn_tasks.append(
                asyncio.create_task(
                    test_alpn(result["endpoint"], result["port"], [proto])
                )
            )

    # No endpoints to check
    if not alpn_tasks:
        return []

    async with sem:
        done_alpn, pending_alpn = await asyncio.wait(alpn_tasks, timeout=TIMEOUT)

    # Cancel pings that don't respond
    for fut in pending_alpn:
        fut.cancel()

    alpns = []
    server_versions = ""
    for task in done_alpn:
        result = task.result()
        server_versions = result["server_versions"]
        alpns.extend(result["ALPN"])

    return {
        "endpoint": endpoint,
        "port": port,
        "ALPN": alpns,
        "server_versions": server_versions,
    }


async def main(endpoints: list[str], ports: list[int]):
    loop = asyncio.get_running_loop()
    loop.set_exception_handler(exception_handler)

    conn = db.connect_db()

    tasks = []
    sem = asyncio.Semaphore(CONCURRENCY)
    for endpoint in endpoints:
        for port in ports:
            tasks.append(asyncio.create_task(quic_map(endpoint, port, sem)))

    results = await tqdm_asyncio.gather(*tasks)

    for result in results:
        if result:
            db.insert_data(conn, result)
            pretty_print(result)

    db.close_db(conn)


if __name__ == "__main__":
    # initiate logger
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - [%(levelname)s] - %(message)s",
        handlers=[
            logging.FileHandler("log/app.log"),
            logging.StreamHandler()
        ]
    )
    logging.info("quicmap Started")
    hosts, ports = parse_arguments()
    asyncio.run(main(hosts, ports))
    logging.info("quicmap Ended")
