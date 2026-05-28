package main

import (
	"flag"
	"fmt"
	"log"
	"net/http"

	"niimbot-helper/internal/api"
	"niimbot-helper/internal/app"
	"niimbot-helper/internal/config"
)

func main() {
	listen := flag.String("listen", "127.0.0.1:9091", "http listen address")
	flag.Parse()

	cfg := config.Default(*listen)
	svc := app.NewBridgeService()
	server := api.New(svc)

	fmt.Printf("niimbot helper listening on http://%s\n", cfg.ListenAddr)
	if err := http.ListenAndServe(cfg.ListenAddr, server.Routes()); err != nil {
		log.Fatalf("server stopped: %v", err)
	}
}
