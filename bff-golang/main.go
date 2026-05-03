package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"os"
	"runtime"
	"time"

	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promhttp"
)

const (
	mockBackendURL = "http://mock-backend:8081/api/data"
	listenAddr     = ":8080"
)

var (
	httpClient = &http.Client{
		Timeout: 30 * time.Second,
	}

	// Prometheus metrics
	requestDuration = prometheus.NewHistogramVec(
		prometheus.HistogramOpts{
			Name:    "bff_request_duration_seconds",
			Help:    "Duration of proxy requests to mock backend",
			Buckets: prometheus.DefBuckets,
		},
		[]string{"status"},
	)
	requestTotal = prometheus.NewCounterVec(
		prometheus.CounterOpts{
			Name: "bff_requests_total",
			Help: "Total number of proxy requests",
		},
		[]string{"status"},
	)
)

func init() {
	prometheus.MustRegister(requestDuration)
	prometheus.MustRegister(requestTotal)
}

func proxyHandler(w http.ResponseWriter, r *http.Request) {
	start := time.Now()

	// Call mock backend
	resp, err := httpClient.Get(mockBackendURL)
	if err != nil {
		log.Printf("Error calling mock backend: %v", err)
		http.Error(w, "Backend unavailable", http.StatusBadGateway)
		requestTotal.WithLabelValues("error").Inc()
		requestDuration.WithLabelValues("error").Observe(time.Since(start).Seconds())
		return
	}
	defer resp.Body.Close()

	// Read full response body into memory (forces allocation)
	buf := make([]byte, 0)
	temp := make([]byte, 32*1024)
	for {
		n, readErr := resp.Body.Read(temp)
		if n > 0 {
			buf = append(buf, temp[:n]...)
		}
		if readErr != nil {
			break
		}
	}

	// Set headers and write response
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(resp.StatusCode)
	w.Write(buf)

	duration := time.Since(start)
	requestTotal.WithLabelValues("success").Inc()
	requestDuration.WithLabelValues("success").Observe(duration.Seconds())
}

func healthHandler(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]string{"status": "UP"})
}

func main() {
	// Limit to 2 CPUs to match container resource limit
	runtime.GOMAXPROCS(2)

	mux := http.NewServeMux()
	mux.HandleFunc("/api/data", proxyHandler)
	mux.HandleFunc("/health", healthHandler)
	mux.Handle("/metrics", promhttp.Handler())

	log.Printf("BFF Golang starting on %s", listenAddr)
	log.Printf("GOMAXPROCS=%d, NumCPU=%d", runtime.GOMAXPROCS(0), runtime.NumCPU())
	log.Printf("Mock backend URL: %s", mockBackendURL)

	server := &http.Server{
		Addr:         listenAddr,
		Handler:      mux,
		ReadTimeout:  10 * time.Second,
		WriteTimeout: 30 * time.Second,
		IdleTimeout:  60 * time.Second,
	}

	if err := server.ListenAndServe(); err != nil {
		fmt.Fprintf(os.Stderr, "Server error: %v\n", err)
		os.Exit(1)
	}
}
