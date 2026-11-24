# How the Internet Works: Lecture Notes

## Packets and protocols

The Internet is a global network of networks that exchange data using shared rules called protocols. Data sent across the Internet is split into small pieces called packets. Each packet travels independently and may take a different route to its destination.

A protocol is a set of rules that defines how computers format and exchange messages. Routers forward packets between networks by reading the destination address in each packet header.

## IP addresses and DNS

An IP address is a numeric label that identifies a device on a network. IPv4 addresses are 32 bits long, which allows about 4.3 billion unique addresses. IPv6 uses 128-bit addresses to solve the shortage of IPv4 addresses.

DNS is the system that translates human-readable domain names into IP addresses. When you type a website name, your computer asks a DNS resolver for the matching IP address before it can connect.

## TCP and UDP

TCP is a connection-oriented protocol that guarantees packets arrive in order and without errors. Before sending data, TCP performs a three-way handshake using SYN, SYN-ACK and ACK messages. If a packet is lost, TCP detects the gap and retransmits the missing data.

UDP is a connectionless protocol that sends packets without checking whether they arrive. Video calls and online games often use UDP because low latency matters more than perfect delivery.

## The web

HTTP is the protocol browsers use to request web pages from servers. HTTPS adds encryption using TLS, so attackers on the network cannot read or modify the traffic. A status code of 404 means the server could not find the requested resource, while 500 signals an error inside the server.

Latency: the time it takes for a packet to travel from source to destination.
Bandwidth: the maximum amount of data that can be transferred per second.
