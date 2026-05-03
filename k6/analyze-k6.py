#!/usr/bin/env python3
"""
k6 Results Analyzer - Extracts a compact summary from k6 NDJSON output.

Usage:
    python analyze-k6.py results/blocking-parallelgc.json

Output:
    - Prints a readable summary to stdout
    - Saves a compact JSON summary to results/summary-<filename>.json
"""

import json
import sys
import os
from collections import defaultdict
import statistics


def analyze_k6_json(filepath):
    """Parse k6 NDJSON file and extract key metrics."""
    
    # Collect raw data
    latencies = []
    statuses = defaultdict(int)
    errors = []
    iterations = 0
    start_time = None
    end_time = None
    data_received = 0
    data_sent = 0
    connect_times = []
    tls_times = []
    sending_times = []
    waiting_times = []
    receiving_times = []
    
    print(f"Analyzing: {filepath}")
    print(f"File size: {os.path.getsize(filepath) / 1024 / 1024:.1f} MB")
    print("Parsing (this may take a moment for large files)...")
    
    with open(filepath, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            
            metric = entry.get('metric', '')
            entry_type = entry.get('type', '')
            data = entry.get('data', {})
            
            # Track time range
            ts = data.get('time', '')
            if ts:
                if start_time is None or ts < start_time:
                    start_time = ts
                if end_time is None or ts > end_time:
                    end_time = ts
            
            # HTTP request duration (latency)
            if metric == 'http_req_duration' and entry_type == 'Point':
                latencies.append(data.get('value', 0))
            
            # HTTP request status (from tags)
            elif metric == 'http_reqs' and entry_type == 'Point':
                tags = data.get('tags', {})
                status = tags.get('status', 'unknown')
                if status != 'unknown':
                    try:
                        status_code = int(status)
                        if 200 <= status_code < 300:
                            statuses['2xx'] += 1
                        elif 400 <= status_code < 500:
                            statuses['4xx'] += 1
                        elif 500 <= status_code < 600:
                            statuses['5xx'] += 1
                        else:
                            statuses[str(status_code)] += 1
                    except ValueError:
                        statuses[status] += 1
                else:
                    statuses['unknown'] += 1
            
            # HTTP request details (connect, tls, send, wait, receive)
            elif metric == 'http_req_connecting' and entry_type == 'Point':
                connect_times.append(data.get('value', 0))
            elif metric == 'http_req_tls_handshaking' and entry_type == 'Point':
                tls_times.append(data.get('value', 0))
            elif metric == 'http_req_sending' and entry_type == 'Point':
                sending_times.append(data.get('value', 0))
            elif metric == 'http_req_waiting' and entry_type == 'Point':
                waiting_times.append(data.get('value', 0))
            elif metric == 'http_req_receiving' and entry_type == 'Point':
                receiving_times.append(data.get('value', 0))
            
            # Iterations
            elif metric == 'iterations' and entry_type == 'Point':
                iterations += 1
            
            # Data transferred
            elif metric == 'data_received' and entry_type == 'Point':
                data_received += data.get('value', 0)
            elif metric == 'data_sent' and entry_type == 'Point':
                data_sent += data.get('value', 0)
            
            # Errors
            elif metric == 'errors' and entry_type == 'Point':
                if data.get('value', 0) > 0:
                    errors.append(data.get('time', ''))
    
    # Calculate statistics
    total_requests = sum(statuses.values())
    
    if latencies:
        latencies_sorted = sorted(latencies)
        n = len(latencies_sorted)
        latency_stats = {
            'count': n,
            'avg_ms': round(statistics.mean(latencies_sorted), 2),
            'min_ms': round(min(latencies_sorted), 2),
            'max_ms': round(max(latencies_sorted), 2),
            'med_ms': round(latencies_sorted[n // 2], 2),
            'p50_ms': round(latencies_sorted[int(n * 0.50)], 2),
            'p90_ms': round(latencies_sorted[int(n * 0.90)], 2),
            'p95_ms': round(latencies_sorted[int(n * 0.95)], 2),
            'p99_ms': round(latencies_sorted[int(n * 0.99)], 2),
            'p999_ms': round(latencies_sorted[int(n * 0.999)], 2) if n > 1000 else round(max(latencies_sorted), 2),
            'stddev_ms': round(statistics.stdev(latencies_sorted), 2) if n > 1 else 0,
        }
    else:
        latency_stats = {'count': 0}
    
    # Calculate test duration
    test_duration_sec = 0
    if start_time and end_time:
        try:
            from datetime import datetime
            start_dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
            end_dt = datetime.fromisoformat(end_time.replace('Z', '+00:00'))
            test_duration_sec = (end_dt - start_dt).total_seconds()
        except Exception:
            pass
    
    # Build summary
    summary = {
        'file': os.path.basename(filepath),
        'test_duration_sec': round(test_duration_sec, 1),
        'start_time': start_time,
        'end_time': end_time,
        'requests': {
            'total': total_requests,
            'rate_per_sec': round(total_requests / test_duration_sec, 1) if test_duration_sec > 0 else 0,
            'status_codes': dict(statuses),
        },
        'latency_ms': latency_stats,
        'request_breakdown_ms': {
            'connect_avg': round(statistics.mean(connect_times), 2) if connect_times else 0,
            'tls_avg': round(statistics.mean(tls_times), 2) if tls_times else 0,
            'sending_avg': round(statistics.mean(sending_times), 2) if sending_times else 0,
            'waiting_avg': round(statistics.mean(waiting_times), 2) if waiting_times else 0,
            'receiving_avg': round(statistics.mean(receiving_times), 2) if receiving_times else 0,
        },
        'iterations': {
            'total': iterations,
            'rate_per_sec': round(iterations / test_duration_sec, 1) if test_duration_sec > 0 else 0,
        },
        'data': {
            'received_mb': round(data_received / 1024 / 1024, 1),
            'sent_mb': round(data_sent / 1024 / 1024, 1),
        },
        'errors': {
            'count': len(errors),
            'error_rate': round(len(errors) / iterations * 100, 2) if iterations > 0 else 0,
        },
    }
    
    # Print readable summary
    print("\n" + "=" * 70)
    print(f"  K6 TEST RESULTS SUMMARY: {os.path.basename(filepath)}")
    print("=" * 70)
    print(f"\n  Duration: {test_duration_sec:.1f}s ({test_duration_sec/60:.1f} min)")
    print(f"  Start:    {start_time}")
    print(f"  End:      {end_time}")
    
    print(f"\n  {'─' * 40}")
    print(f"  HTTP STATUS CODES")
    print(f"  {'─' * 40}")
    print(f"  Total Requests:  {total_requests:,}")
    for code, count in sorted(statuses.items()):
        pct = (count / total_requests * 100) if total_requests > 0 else 0
        print(f"  {code:>6}:  {count:>10,}  ({pct:.2f}%)")
    
    print(f"\n  {'─' * 40}")
    print(f"  LATENCY (ms)")
    print(f"  {'─' * 40}")
    if latency_stats.get('count', 0) > 0:
        print(f"  Avg:     {latency_stats['avg_ms']:>10.2f}")
        print(f"  Min:     {latency_stats['min_ms']:>10.2f}")
        print(f"  Med:     {latency_stats['med_ms']:>10.2f}")
        print(f"  Max:     {latency_stats['max_ms']:>10.2f}")
        print(f"  StdDev:  {latency_stats['stddev_ms']:>10.2f}")
        print(f"  p50:     {latency_stats['p50_ms']:>10.2f}")
        print(f"  p90:     {latency_stats['p90_ms']:>10.2f}")
        print(f"  p95:     {latency_stats['p95_ms']:>10.2f}")
        print(f"  p99:     {latency_stats['p99_ms']:>10.2f}")
        print(f"  p99.9:   {latency_stats['p999_ms']:>10.2f}")
    
    print(f"\n  {'─' * 40}")
    print(f"  REQUEST BREAKDOWN (avg ms)")
    print(f"  {'─' * 40}")
    brk = summary['request_breakdown_ms']
    print(f"  Connect:    {brk['connect_avg']:>8.2f}")
    print(f"  TLS:        {brk['tls_avg']:>8.2f}")
    print(f"  Sending:    {brk['sending_avg']:>8.2f}")
    print(f"  Waiting:    {brk['waiting_avg']:>8.2f}")
    print(f"  Receiving:  {brk['receiving_avg']:>8.2f}")
    
    print(f"\n  {'─' * 40}")
    print(f"  THROUGHPUT")
    print(f"  {'─' * 40}")
    print(f"  Requests/sec:  {summary['requests']['rate_per_sec']:>10.1f}")
    print(f"  Iterations:    {iterations:>10,}")
    print(f"  Iter/sec:      {summary['iterations']['rate_per_sec']:>10.1f}")
    print(f"  Data Received: {summary['data']['received_mb']:>8.1f} MB")
    print(f"  Data Sent:     {summary['data']['sent_mb']:>8.1f} MB")
    
    print(f"\n  {'─' * 40}")
    print(f"  ERRORS")
    print(f"  {'─' * 40}")
    print(f"  Error Count:   {len(errors):>10,}")
    print(f"  Error Rate:    {summary['errors']['error_rate']:>9.2f}%")
    
    print("\n" + "=" * 70)
    
    # Save summary JSON
    base_name = os.path.splitext(os.path.basename(filepath))[0]
    summary_path = os.path.join(os.path.dirname(filepath), f"summary-{base_name}.json")
    with open(summary_path, 'w', encoding='utf-8') as f:
        json.dump(summary, f, indent=2)
    print(f"\n  Summary saved to: {summary_path}")
    
    return summary


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python analyze-k6.py <k6-results.json>")
        print("Example: python analyze-k6.py results/blocking-parallelgc.json")
        sys.exit(1)
    
    filepath = sys.argv[1]
    if not os.path.exists(filepath):
        print(f"Error: File not found: {filepath}")
        sys.exit(1)
    
    analyze_k6_json(filepath)
