; 基本设置
!define PRODUCT_NAME "Financial Automation"
!define PRODUCT_PUBLISHER "JeuneAstre"
!define PRODUCT_WEB_SITE "https://jeuneastre.com"
!define PRODUCT_DIR_REGKEY "Software\Microsoft\Windows\CurrentVersion\App Paths\FinancialAutomation.exe"
!define PRODUCT_UNINST_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\${PRODUCT_NAME}"
!define PRODUCT_UNINST_ROOT_KEY "HKLM"

; 添加常量定义
!define APP_DATA_DIR "$LOCALAPPDATA\Financial Automation"
!define APP_CONFIG_DIR "$LOCALAPPDATA\Financial Automation\config"
!define APP_LOGS_DIR "$LOCALAPPDATA\Financial Automation\logs"
!define APP_ASSETS_DIR "$LOCALAPPDATA\Financial Automation\assets"

SetCompressor lzma
Name "${PRODUCT_NAME} ${PRODUCT_VERSION}"
OutFile "Financial_Automation_Setup_${PRODUCT_VERSION}.exe"
InstallDir "$PROGRAMFILES\Financial Automation"
InstallDirRegKey HKLM "${PRODUCT_DIR_REGKEY}" ""
ShowInstDetails show
ShowUnInstDetails show

; MUI 现代界面定义
!include "MUI2.nsh"

!define MUI_ABORTWARNING
!define MUI_ICON "${NSISDIR}\Contrib\Graphics\Icons\modern-install.ico"
!define MUI_UNICON "${NSISDIR}\Contrib\Graphics\Icons\modern-uninstall.ico"

; 欢迎页面
!insertmacro MUI_PAGE_WELCOME
; 许可协议页面
!insertmacro MUI_PAGE_LICENSE "License.txt"
; 安装目录选择页面
!insertmacro MUI_PAGE_DIRECTORY
; 安装过程页面
!insertmacro MUI_PAGE_INSTFILES
; 安装完成页面
!insertmacro MUI_PAGE_FINISH

; 卸载页面
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

; 语言文件
!insertmacro MUI_LANGUAGE "SimpChinese"

Section "MainSection" SEC01
    SetOutPath "$INSTDIR"
    SetOverwrite ifnewer
    
    ; 安装主程序文件
    File /r "main.dist\*.*"
    
    ; 创建数据目录
    CreateDirectory "${APP_DATA_DIR}"
    CreateDirectory "${APP_CONFIG_DIR}"
    CreateDirectory "${APP_LOGS_DIR}"
    CreateDirectory "${APP_ASSETS_DIR}"
    
    ; 复制配置文件和资源文件
    SetOutPath "${APP_CONFIG_DIR}"
    File /r "config\*.*"
    
    SetOutPath "${APP_ASSETS_DIR}"
    File /r "assets\*.*"
    
    ; 创建开始菜单快捷方式
    CreateDirectory "$SMPROGRAMS\Financial Automation"
    CreateShortCut "$SMPROGRAMS\Financial Automation\Financial Automation.lnk" "$INSTDIR\FinancialAutomation.exe"
    CreateShortCut "$DESKTOP\Financial Automation.lnk" "$INSTDIR\FinancialAutomation.exe"
    
    ; 写入卸载信息到注册表
    WriteUninstaller "$INSTDIR\uninst.exe"
    WriteRegStr HKLM "${PRODUCT_DIR_REGKEY}" "" "$INSTDIR\FinancialAutomation.exe"
    WriteRegStr ${PRODUCT_UNINST_ROOT_KEY} "${PRODUCT_UNINST_KEY}" "DisplayName" "$(^Name)"
    WriteRegStr ${PRODUCT_UNINST_ROOT_KEY} "${PRODUCT_UNINST_KEY}" "UninstallString" "$INSTDIR\uninst.exe"
    WriteRegStr ${PRODUCT_UNINST_ROOT_KEY} "${PRODUCT_UNINST_KEY}" "DisplayIcon" "$INSTDIR\FinancialAutomation.exe"
    WriteRegStr ${PRODUCT_UNINST_ROOT_KEY} "${PRODUCT_UNINST_KEY}" "DisplayVersion" "${PRODUCT_VERSION}"
    WriteRegStr ${PRODUCT_UNINST_ROOT_KEY} "${PRODUCT_UNINST_KEY}" "URLInfoAbout" "${PRODUCT_WEB_SITE}"
    WriteRegStr ${PRODUCT_UNINST_ROOT_KEY} "${PRODUCT_UNINST_KEY}" "Publisher" "${PRODUCT_PUBLISHER}"
    
    ; 创建版本配置文件
    FileOpen $0 "${APP_CONFIG_DIR}\version.json" w
    FileWrite $0 '{"version": "${PRODUCT_VERSION}"}'
    FileClose $0
    
    # 设置系统环境变量
    WriteRegExpandStr HKLM "SYSTEM\CurrentControlSet\Control\Session Manager\Environment" "APP_ENV" "production"
    SendMessage ${HWND_BROADCAST} ${WM_WININICHANGE} 0 "STR:Environment" /TIMEOUT=5000
SectionEnd

Section Uninstall
    Delete "$SMPROGRAMS\Financial Automation\Financial Automation.lnk"
    Delete "$DESKTOP\Financial Automation.lnk"
    RMDir "$SMPROGRAMS\Financial Automation"
    
    ; 删除程序文件
    RMDir /r "$INSTDIR"
    
    ; 删除数据目录
    RMDir /r "${APP_DATA_DIR}"
    
    ; 删除注册表项
    DeleteRegKey ${PRODUCT_UNINST_ROOT_KEY} "${PRODUCT_UNINST_KEY}"
    DeleteRegKey HKLM "${PRODUCT_DIR_REGKEY}"
    
    # 删除环境变量
    DeleteRegValue HKLM "SYSTEM\CurrentControlSet\Control\Session Manager\Environment" "APP_ENV"
    SendMessage ${HWND_BROADCAST} ${WM_WININICHANGE} 0 "STR:Environment" /TIMEOUT=5000
SectionEnd
