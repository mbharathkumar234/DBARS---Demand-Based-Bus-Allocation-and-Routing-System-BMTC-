# Start entire project (Backend + Frontend)
$backendProcess = Start-Process powershell -ArgumentList "-Command `"cd $PSScriptRoot\backend; .\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000`"" -PassThru
$frontendProcess = Start-Process powershell -ArgumentList "-Command `"cd $PSScriptRoot\frontend; npm run dev`"" -PassThru

Write-Host "Backend process ID: $($backendProcess.Id)"
Write-Host "Frontend process ID: $($frontendProcess.Id)"
Write-Host ""
Write-Host "Backend running at: http://localhost:8000"
Write-Host "Frontend running at: http://localhost:5173"
Write-Host ""
Write-Host "Press Ctrl+C to stop both services"

# Wait for both processes
Wait-Process -Id $backendProcess.Id
Wait-Process -Id $frontendProcess.Id
