@echo off
cd /d "C:\Users\karth\Downloads\ANDY\invoice_data_extraction"
del "C:\Users\karth\Downloads\ANDY\invoice_data_extraction\push_deploy_log.txt" 2>nul
git push origin phase12-first-customer-ready > "C:\Users\karth\Downloads\ANDY\invoice_data_extraction\push_deploy_log.txt" 2>&1
echo EXITCODE=%ERRORLEVEL% >> "C:\Users\karth\Downloads\ANDY\invoice_data_extraction\push_deploy_log.txt"
