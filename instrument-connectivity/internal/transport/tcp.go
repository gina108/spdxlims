package transport

import (
    "net"
    "time"
)

type TCPDialer struct{}
func (d TCPDialer) Probe(address string, timeout time.Duration) error { conn, err := net.DialTimeout("tcp", address, timeout); if err != nil { return err }; return conn.Close() }
