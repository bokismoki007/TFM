for %%u in (10 20 30 40 50 60 70 80 90 100) do (
    echo running test with %%u users

    call locust -f analyzer/locustfile.py --host http://127.0.0.1:8000 --headless -u %%u -r %%u --run-time 60s --csv=results_%%u
    
    timeout /t 2 >nul
    
    powershell -Command "$data = Get-Content results_%%u_stats.csv | Where-Object { $_ -match '\d' }; $data[-1] | Out-File -FilePath all_results.csv -Append -Encoding utf8"
)