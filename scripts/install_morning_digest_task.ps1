# Installe une tâche planifiée Windows qui envoie la Matinale tous les jours à 8h.
#
# À lancer une fois en PowerShell admin :
#   .\scripts\install_morning_digest_task.ps1
#
# Pour désinstaller :
#   schtasks /delete /tn "Triskell Matinale" /f

param(
    [string]$Time = "08:00",
    [string]$TaskName = "Triskell Matinale"
)

$ErrorActionPreference = "Stop"

# Trouve l'exécutable Python (py launcher si dispo, sinon python.exe)
$python = (Get-Command py -ErrorAction SilentlyContinue)?.Source
if (-not $python) {
    $python = (Get-Command python -ErrorAction SilentlyContinue)?.Source
}
if (-not $python) {
    Write-Error "Python introuvable dans le PATH."
    exit 1
}

# Dossier du projet (racine = parent de scripts/)
$projectRoot = Split-Path $PSScriptRoot -Parent

# Commande planifiée : cd <project> && python -m triskell_command.integrations.morning_mailer
$cmd = "cmd.exe"
$args = "/c cd /d `"$projectRoot`" && `"$python`" -m triskell_command.integrations.morning_mailer"

Write-Host "Installation de la tâche '$TaskName' à $Time tous les jours."
Write-Host "Working dir : $projectRoot"
Write-Host "Python      : $python"
Write-Host ""

schtasks /create /tn "$TaskName" /tr "$cmd $args" /sc daily /st $Time /f
if ($LASTEXITCODE -ne 0) {
    Write-Error "schtasks /create a échoué."
    exit $LASTEXITCODE
}

Write-Host ""
Write-Host "Tâche créée. Vérification :"
schtasks /query /tn "$TaskName"
Write-Host ""
Write-Host "Pour la déclencher manuellement (test) :"
Write-Host "  schtasks /run /tn `"$TaskName`""
