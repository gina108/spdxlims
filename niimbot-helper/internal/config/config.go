package config

type Config struct {
	ListenAddr string
}

func Default(listen string) Config {
	if listen == "" {
		listen = "127.0.0.1:9091"
	}
	return Config{ListenAddr: listen}
}
