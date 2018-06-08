import codecs, json, re, os, platform, shutil, sys, threading, time, traceback;

"""
                          __                     _____________                  
            ,,,     _,siSS**SSis,_        ,-.   /             |                 
           :O()   ,SP*'`      `'*YS,     |   `-|  O    BugId  |                 
            ```  dS'  _    |    _ 'Sb   ,'      \_____________|                 
      ,,,       dP     \,-` `-<`    Yb _&/                                      
     :O()      ,S`  \,' \      \    `Sis|ssssssssssssssssss,        ,,,         
      ```      (S   (   | --====)    SSS|SSSSSSSSSSSSSSSSSSD        ()O:        
               'S,  /', /      /    ,S?*/******************'        ```         
                Yb    _/'-_ _-<._   dP `                                        
  _______________YS,       |      ,SP_________________________________________  
                  `Sbs,_      _,sdS`                                            
                    `'*YSSssSSY*'`                   https://bugid.skylined.nl  
                          ``                                                    
                                                                                
""";
# Running this script will return an exit code, which translates as such:
# 0 = executed successfully, no bugs found.
# 1 = executed successfully, bug detected.
# 2 = bad arguments
# 3 = internal error
# 4 = failed to start process or attach to process(es).
# 5 = license error

# Augment the search path: look in main folder, parent folder or "modules" child folder, in that order.
sMainFolderPath = os.path.abspath(os.path.dirname(__file__));
sParentFolderPath = os.path.normpath(os.path.join(sMainFolderPath, ".."));
sModulesFolderPath = os.path.join(sMainFolderPath, "modules");
asOriginalSysPath = sys.path[:];
sys.path = [sMainFolderPath, sParentFolderPath, sModulesFolderPath] + sys.path;

# Load external dependecies to make sure they are available and shown an error
# if any one fails to load. This error explains where the missing component
# can be downloaded to fix the error.
for (sModuleName, sDownloadURL) in [
  ("cBugId", "https://github.com/SkyLined/cBugId/"),
  ("mFileSystem", "https://github.com/SkyLined/mFileSystem/"),
  ("mProductDetails", "https://github.com/SkyLined/mProductDetails/"),
  ("mWindowsAPI", "https://github.com/SkyLined/mWindowsAPI/"),
  ("oConsole", "https://github.com/SkyLined/oConsole/"),
]:
  try:
    __import__(sModuleName, globals(), locals(), [], -1);
  except ImportError as oError:
    if oError.message == "No module named %s" % sModuleName:
      print "*" * 80;
      print "BugId depends on %s which you can download at:" % sModuleName;
      print "    %s" % sDownloadURL;
      print "After downloading, please save the code in this folder:";
      print "    %s" % os.path.join(sModuleFolderPath, sModuleName);
      print " - or -";
      print "    %s" % os.path.join(sParentFolderPath, sModuleName);
      print "Once you have completed these steps, please try again.";
      print "*" * 80;
    raise;

import cBugId, mFileSystem, mProductDetails, mWindowsAPI, oConsole;

# Restore the search path
sys.path = asOriginalSysPath;

from cBugId import cBugId;
from oConsole import oConsole;
# Augment the search path to access BugId internals.
sys.path = [sMainFolderPath] + sys.path;
from ddxApplicationSettings_by_sKeyword import ddxApplicationSettings_by_sKeyword;
from dxConfig import dxConfig;
from fbApplyConfigSetting import fbApplyConfigSetting;
from fPrintApplicationKeyWordHelp import fPrintApplicationKeyWordHelp;
from fPrintExceptionInformation import fPrintExceptionInformation;
from fPrintLogo import fPrintLogo;
from fPrintUsageInformation import fPrintUsageInformation;
from fPrintVersionInformation import fPrintVersionInformation;
from mColors import *;

gasAttachToProcessesForExecutableNames = [];
gasBinaryNamesThatAreAllowedToRunWithoutPageHeap = [
  "conhost.exe", # Used to create console windows, not part of the target application (unless that is conhost :)
];
gasReportedBinaryNameWithoutPageHeap = [];
gbAnErrorOccured = False;
gbFailedToApplyMemoryLimitsErrorShown = False;
gbQuiet = False;
gbVerbose = False;
guDefaultCollateralMaximumNumberOfBugs = 5; # Just a hunch that that's a reasonable value.
guDetectedBugsCount = 0;
guMaximumNumberOfBugs = 1;
gduNumberOfRepros_by_sBugIdAndLocation = {};

def fApplicationMaxRunTimeCallback(oBugId):
  oConsole.fPrint("+ T+%.1f The application has been running for %.1f seconds without crashing." % \
      (oBugId.fnApplicationRunTime(), dxConfig["nApplicationMaxRunTime"]));
  oConsole.fPrint();
  oConsole.fStatus(INFO, "* BugId is stopping...");
  oBugId.fStop();

def fApplicationResumedCallback(oBugId):
  oConsole.fStatus("* The application is running...");

def fApplicationRunningCallback(oBugId):
  oConsole.fStatus("* The application was started successfully and is running...");

def fApplicationSuspendedCallback(oBugId, sReason):
  oConsole.fStatus("* T+%.1f The application is suspended (%s)..." % (oBugId.fnApplicationRunTime(), sReason));

def fFailedToDebugApplicationCallback(oBugId, sErrorMessage):
  global gbAnErrorOccured;
  gbAnErrorOccured = True;
  oConsole.fLock();
  try:
    oConsole.fPrint(ERROR, u"\u250C\u2500", ERROR_INFO, " Failed to debug the application ", ERROR, sPadding = u"\u2500");
    for sLine in sErrorMessage.split("\n"):
      oConsole.fPrint(ERROR, u"\u2502 ", ERROR_INFO, sLine.rstrip("\r"));
    oConsole.fPrint(ERROR, u"\u2514", sPadding = u"\u2500");
    oConsole.fPrint();
  finally:
    oConsole.fUnlock();

def fInternalExceptionCallback(oBugId, oException, oTraceBack):
  global gbAnErrorOccured;
  gbAnErrorOccured = True;
  fPrintExceptionInformation(oException, oTraceBack);
  oConsole.fCleanup();
  os._exit(3);

def fLicenseErrorsCallback(oBugId, asErrors):
  # These should have been reported before cBugId was even instantiated, so this is kind of unexpected.
  # But rather than raise AssertionError("NOT REACHED"), we'll report the license error gracefully:
  global gbAnErrorOccured;
  gbAnErrorOccured = True;
  oConsole.fLock();
  try:
    oConsole.fPrint(ERROR, u"\u250C\u2500", ERROR_INFO, " Software license error ", ERROR, sPadding = u"\u2500");
    for sError in asErrors:
      oConsole.fPrint(ERROR, u"\u2502 ", ERROR_INFO, sError);
    oConsole.fPrint(ERROR, u"\u2514", sPadding = u"\u2500");
  finally:
    oConsole.fUnlock();
  os._exit(5);

def fLicenseWarningsCallback(oBugId, asWarnings):
  # These were already reported when BugId started; ignore them.
  pass;
#  oConsole.fLock();
#  try:
#    oConsole.fPrint(WARNING, u"\u250C\u2500", WARNING_INFO, " Warning ", WARNING, sPadding = u"\u2500");
#    for sWarning in asWarnings:
#      oConsole.fPrint(WARNING, u"\u2502 ", WARNING_INFO, sWarning);
#    oConsole.fPrint(WARNING, u"\u2514", sPadding = u"\u2500");
#  finally:
#    oConsole.fUnlock();

def fPageHeapNotEnabledCallback(oBugId, oProcessInformation, bIsMainProcess, bPreventable):
  global \
      gasAttachToProcessesForExecutableNames, \
      gasBinaryNamesThatAreAllowedToRunWithoutPageHeap, \
      gasReportedBinaryNameWithoutPageHeap, \
      gbAnErrorOccured;
  sBinaryName = oProcessInformation.sBinaryName;
  
  if sBinaryName.lower() in gasBinaryNamesThatAreAllowedToRunWithoutPageHeap:
    return;
  if not bPreventable:
    if not gbQuiet and sBinaryName not in gasReportedBinaryNameWithoutPageHeap:
      gasReportedBinaryNameWithoutPageHeap.append(sBinaryName);
      oConsole.fLock();
      try:
        oConsole.fPrint(ERROR,"- Full page heap is not enabled for ", ERROR_INFO, sBinaryName, ERROR,".");
        oConsole.fPrint("  This appears to be due to a bug in page heap that prevents it from");
        oConsole.fPrint("  determining the binary name correctly. Unfortunately, there is no known fix");
        oConsole.fPrint("  or work-around for this. BugId will continue, but detection and analysis of");
        oConsole.fPrint("  any bugs in this process will be sub-optimal.");
        oConsole.fPrint();
      finally:
        oConsole.fUnlock();
  else:
    gbAnErrorOccured = True;
    oConsole.fLock();
    try:
      oConsole.fPrint(ERROR, "- Full page heap is not enabled for all binaries used by the application.");
      oConsole.fPrint(ERROR, "  Specifically it is not enabled for ", ERROR_INFO, sBinaryName, ERROR,".");
      oConsole.fPrint("  You can enabled full page heap for ", sBinaryName, " by running:");
      oConsole.fPrint();
      oConsole.fPrint("      ", INFO, 'PageHeap.cmd "', sBinaryName, '" ON');
      oConsole.fPrint();
      oConsole.fPrint("  Without page heap enabled, detection and anaylsis of any bugs will be sub-");
      oConsole.fPrint("  optimal. Please enable page heap and try again.");
      oConsole.fPrint();
      oConsole.fStatus(INFO, "* BugId is stopping...");
    finally:
      oConsole.fUnlock();
    # There is no reason to run without page heap, so terminated.
    oBugId.fStop();
    # If you really want to run without page heap, set `dxConfig["cBugId"]["bEnsurePageHeap"]` to `False` in
    # `dxConfig.py`or run with the command-line siwtch `--cBugId.bEnsurePageHeap=false`

def fCdbStdInInputCallback(oBugId, sInput):
  oConsole.fPrint(HILITE, "<stdin<", NORMAL, sInput, uConvertTabsToSpaces = 8);
def fCdbStdOutOutputCallback(oBugId, sOutput):
  oConsole.fPrint(HILITE, "stdout>", NORMAL, sOutput, uConvertTabsToSpaces = 8);
def fCdbStdErrOutputCallback(oBugId, sOutput):
  oConsole.fPrint(ERROR_INFO, "stderr>", ERROR, sOutput, uConvertTabsToSpaces = 8);
def fLogMessageCallback(oBugId, sMessage, dsData = None):
  sData = dsData and ", ".join(["%s: %s" % (sName, sValue) for (sName, sValue) in dsData.items()]);
  oConsole.fPrint(DIM, "log>%s%s" % (sMessage, sData and " (%s)" % sData or ""));

# Helper function to format messages that are specific to a process.
def fPrintMessageForProcess(sHeaderChar, oProcess, bIsMainProcess, *asMessage):
  # oProcess is either a mWindowsAPI.cConsoleProcess or mWindowsAPI.cProcessInformation instance.
  oConsole.fPrint(
    sHeaderChar, " ", bIsMainProcess and "Main" or "Sub", " process ",
    INFO, "%d" % oProcess.uId, NORMAL, "/", INFO , "0x%X" % oProcess.uId, NORMAL,
    " (", INFO, oProcess.sBinaryName, NORMAL, "): ",
    *asMessage,
    uConvertTabsToSpaces = 8
  );

def fFailedToApplyApplicationMemoryLimitsCallback(oBugId, oProcessInformation, bIsMainProcess):
  global gbFailedToApplyMemoryLimitsErrorShown, gbQuiet, gbVerbose;
  if not gbQuiet:
    fPrintMessageForProcess("-", oProcessInformation, bIsMainProcess,
        ERROR_INFO, "Cannot apply application memory limits");
    gbFailedToApplyMemoryLimitsErrorShown = True;
    if not gbVerbose:
      oConsole.fPrint("  Any additional failures to apply memory limits to processess will not be shown.");
def fFailedToApplyProcessMemoryLimitsCallback(oBugId, oProcessInformation, bIsMainProcess):
  global gbFailedToApplyMemoryLimitsErrorShown, gbVerbose;
  if gbVerbose or not gbFailedToApplyMemoryLimitsErrorShown:
    fPrintMessageForProcess("-", oProcessInformation, bIsMainProcess,
        ERROR_INFO, "Cannot apply process memory limits");
    gbFailedToApplyMemoryLimitsErrorShown = True;
    if not gbVerbose:
      oConsole.fPrint("  Any additional failures to apply memory limits to processess will not be shown.");

def fProcessStartedCallback(oBugId, oConsoleProcess, bIsMainProcess):
  if gbVerbose:
    fPrintMessageForProcess("+", oConsoleProcess, bIsMainProcess,
      "Started", "; command line = ", INFO, oConsoleProcess.sCommandLine, NORMAL, "."
    );
def fProcessAttachedCallback(oBugId, oProcessInformation, bIsMainProcess):
  global gasAttachToProcessesForExecutableNames;
  if not gbQuiet: # Main processes
    fPrintMessageForProcess("+", oProcessInformation, bIsMainProcess,
      "Attached", "; command line = ", INFO, oProcessInformation.sCommandLine or "<unknown>", NORMAL, "."
    );
  # Now is a good time to look for additional binaries that may need to be debugged as well.
  if gasAttachToProcessesForExecutableNames:
    oBugId.fAttachToProcessesForExecutableNames(*gasAttachToProcessesForExecutableNames);

def fApplicationDebugOutputCallback(oBugId, oProcessInformation, bIsMainProcess, asMessages):
  uCount = 0;
  for sMessage in asMessages:
    uCount += 1;
    if uCount == 1:
      sHeader = "*";
      uPrefixColor = INFO;
      sPrefix = "debug";
    else:
      sHeader = " ";
      uPrefixColor = DIM;
      if uCount == len(asMessages):
        sPrefix = u"  \u2514\u2500\u2500";
      else:
        sPrefix = u"  \u2502  ";
    fPrintMessageForProcess(sHeader, oProcessInformation, bIsMainProcess,
      uPrefixColor, sPrefix, NORMAL, ">", HILITE, sMessage,
    );

def fApplicationStdOutOutputCallback(oBugId, oConsoleProcess, bIsMainProcess, sMessage):
  fPrintMessageForProcess("*", oConsoleProcess, bIsMainProcess,
    INFO, "stdout", NORMAL, ">", HILITE, sMessage,
  );
def fApplicationStdErrOutputCallback(oBugId, oConsoleProcess, bIsMainProcess, sMessage):
  fPrintMessageForProcess("*", oConsoleProcess, bIsMainProcess,
    ERROR, "stderr", NORMAL, ">", ERROR_INFO, sMessage,
  );

def fProcessTerminatedCallback(oBugId, oProcessInformation, bIsMainProcess):
  bStopBugId = bIsMainProcess and dxConfig["bApplicationTerminatesWithMainProcess"];
  if not gbQuiet:
    fPrintMessageForProcess("-", oProcessInformation, bIsMainProcess,
      "Terminated", bStopBugId and "; the application is considered to have terminated with it." or ".",
    );
  if bStopBugId:
    oConsole.fStatus(INFO, "* BugId is stopping because a main process terminated...");
    oBugId.fStop();

def fBugReportCallback(oBugId, oBugReport):
  global guDetectedBugsCount, \
         guMaximumNumberOfBugs, \
         gduNumberOfRepros_by_sBugIdAndLocation;
  guDetectedBugsCount += 1;
  oConsole.fLock();
  try:
    oConsole.fPrint(u"\u250C\u2500 ", HILITE, "A bug was detect in the application ", NORMAL, sPadding = u"\u2500");
    if oBugReport.sBugLocation:
      oConsole.fPrint(u"\u2502 Id @ Location:    ", INFO, oBugReport.sId, NORMAL, " @ ", INFO, oBugReport.sBugLocation);
      sBugIdAndLocation = "%s @ %s" % (oBugReport.sId, oBugReport.sBugLocation);
    else:
      oConsole.fPrint(u"\u2502 Id:               ", INFO, oBugReport.sId);
      sBugIdAndLocation = oBugReport.sId;
    gduNumberOfRepros_by_sBugIdAndLocation.setdefault(sBugIdAndLocation, 0);
    gduNumberOfRepros_by_sBugIdAndLocation[sBugIdAndLocation] += 1;
    if oBugReport.sBugSourceLocation:
      oConsole.fPrint(u"\u2502 Source:           ", INFO, oBugReport.sBugSourceLocation);
    oConsole.fPrint(u"\u2502 Description:      ", INFO, oBugReport.sBugDescription);
    oConsole.fPrint(u"\u2502 Security impact:  ", INFO, oBugReport.sSecurityImpact);
    oConsole.fPrint(u"\u2502 Version:          ", NORMAL, oBugReport.asVersionInformation[0]); # The process' binary.
    for sVersionInformation in oBugReport.asVersionInformation[1:]: # There may be two if the crash was in a
      oConsole.fPrint(u"\u2502                   ", NORMAL, sVersionInformation); # different binary (e.g. a .dll)
    if dxConfig["bGenerateReportHTML"]:
      # Use a report file name base on the BugId.
      sDesiredReportFileName = "%s.html" % sBugIdAndLocation;
      # In collateral mode, we will number the reports so you know in which order bugs were reported.
      if guMaximumNumberOfBugs > 1:
        sDesiredReportFileName = "#%d %s" % (guDetectedBugsCount, sDesiredReportFileName);
      # Translate characters that are not valid in file names.
      sValidReportFileName = mFileSystem.fsValidName(sDesiredReportFileName, bUnicode = \
          dxConfig["bUseUnicodeReportFileNames"]);
      if dxConfig["sReportFolderPath"] is not None:
        sReportFilePath = mFileSystem.fsPath(dxConfig["sReportFolderPath"], sValidReportFileName);
      else:
        sReportFilePath = mFileSystem.fsPath(sValidReportFileName);
      eWriteDataToFileResult = mFileSystem.feWriteDataToFile(
        oBugReport.sReportHTML,
        sReportFilePath,
        fbRetryOnFailure = lambda: False,
      );
      if eWriteDataToFileResult:
        oConsole.fPrint(u"\u2502 Bug report:       ", ERROR, "Cannot be saved (", \
            ERROR_INFO, repr(eWriteDataToFileResult), ERROR, ")");
      else:
        oConsole.fPrint(u"\u2502 Bug report:       ", NORMAL, sValidReportFileName,  \
            " (%d bytes)" % len(oBugReport.sReportHTML));
    oConsole.fPrint(u"\u2514", sPadding = u"\u2500");
  finally:
    oConsole.fUnlock();

def fMain(asArguments):
  global \
      gasAttachToProcessesForExecutableNames, \
      gasBinaryNamesThatAreAllowedToRunWithoutPageHeap, \
      gbQuiet, \
      gbVerbose, \
      guDetectedBugsCount, \
      guMaximumNumberOfBugs;
  
  # Make sure the Python binary is up to date; we don't want our users to unknowingly run outdated software as this is
  # likely to cause unexpected issues.
  asVersionComponent = platform.python_version().split(".");
  auExpectedVersionComponent = [2, 7, 14];
  for uIndex in xrange(3):
    uVersionComponent = long(asVersionComponent[uIndex]);
    if uVersionComponent < auExpectedVersionComponent[uIndex]:
      oConsole.fPrint(ERROR, "You are running an old version of Python. Please update before using BugId.");
      oConsole.fCleanup();
      os._exit(3);
    elif uVersionComponent > auExpectedVersionComponent[uIndex]:
      oConsole.fPrint(WARNING, "You are running a version of Python on which this version of BugId has not been tested.");
      break;
    
  # Show usage information if no arguments are provided:
  if len(asArguments) == 0:
    fPrintLogo();
    fPrintUsageInformation(ddxApplicationSettings_by_sKeyword.keys());
    oConsole.fCleanup();
    os._exit(0);
  
  # Parse all arguments until we encounter "--".
  sApplicationKeyword = None;
  sApplicationBinaryPath = None;
  auApplicationProcessIds = [];
  sUWPApplicationPackageName = None;
  sUWPApplicationId = None;
  asApplicationOptionalArguments = None;
  sApplicationISA = None;
  bRepeat = False;
  uNumberOfRepeats = None;
  bCheckForUpdates = False;
  dxUserProvidedConfigSettings = {};
  asAdditionalLocalSymbolPaths = [];
  bFast = False;
  while asArguments:
    sArgument = asArguments.pop(0);
    if sArgument == "--":
      if len(auApplicationProcessIds) > 0:
      # The rest of the arguments are to be passed to the application
        oConsole.fPrint(ERROR, "- You cannot provide process ids and application arguments.");
        oConsole.fCleanup();
        os._exit(2);
      asApplicationOptionalArguments = asArguments;
      break;
    elif sArgument in ["-q", "/q"]:
      gbQuiet = True;
    elif sArgument in ["-v", "/v"]:
      gbVerbose = True;
    elif sArgument in ["-f", "/f"]:
      bFast = True;
    elif sArgument in ["-r", "/r"]:
      bRepeat = True;
    elif sArgument in ["-c", "/c"]:
      guMaximumNumberOfBugs = guDefaultCollateralMaximumNumberOfBugs;
    elif sArgument in ["-?", "/?", "-h", "/h"]:
      fPrintLogo();
      fPrintUsageInformation(ddxApplicationSettings_by_sKeyword.keys());
      oConsole.fCleanup();
      os._exit(0);
    elif sArgument.startswith("--"):
      if "=" in sArgument:
        sSettingName, sValue = sArgument[2:].split("=", 1);
      else:
        # "--bFlag" is an alias for "--bFlag=true"
        sSettingName = sArgument[2:];
        sValue = None;
      
      if sSettingName in ["pid", "pids"]:
        if not sValue:
          oConsole.fPrint(ERROR, "- You must provide at least one process id.");
          oConsole.fCleanup();
          os._exit(2);
        if sApplicationBinaryPath is not None:
          oConsole.fPrint(ERROR, "- You cannot provide an application binary and process ids.");
          oConsole.fCleanup();
          os._exit(2);
        if sUWPApplicationPackageName is not None:
          oConsole.fPrint(ERROR, "- You cannot provide an UWP application package name and process ids.");
          oConsole.fCleanup();
          os._exit(2);
        auApplicationProcessIds += [long(x) for x in sValue.split(",")];
      elif sSettingName in ["uwp", "uwp-app"]:
        if not sValue:
          oConsole.fPrint(ERROR, "- You must provide an UWP application package name.");
          oConsole.fCleanup();
          os._exit(2);
        if sUWPApplicationPackageName is not None:
          oConsole.fPrint(ERROR, "- You cannot provide multiple UWP application package names.");
          oConsole.fCleanup();
          os._exit(2);
        if sApplicationBinaryPath is not None:
          oConsole.fPrint(ERROR, "- You cannot provide an application binary and UWP package name.");
          oConsole.fCleanup();
          os._exit(2);
        if len(auApplicationProcessIds) > 0:
          oConsole.fPrint(ERROR, "- You cannot provide process ids and an UWP application package name.");
          oConsole.fCleanup();
          os._exit(2);
        if "!" not in sValue:
          oConsole.fPrint(ERROR, "- Please provide a string of the form ", ERROR_INFO, sSettingName, \
              "=<package name>!<application id>.");
          oConsole.fCleanup();
          os._exit(2);
        sUWPApplicationPackageName, sUWPApplicationId = sValue.split("!", 1);
      elif sSettingName in ["help"]:
        fPrintLogo();
        fPrintUsageInformation(ddxApplicationSettings_by_sKeyword.keys());
        oConsole.fCleanup();
        os._exit(0);
      elif sSettingName in ["version", "check-for-updates"]:
        fPrintVersionInformation(
          bCheckForUpdates = True,
          bCheckAndShowLicenses = True,
          bShowInstallationFolders = True,
        );
        oConsole.fCleanup();
        os._exit(0);
      elif sSettingName in ["isa", "cpu"]:
        if not sValue:
          oConsole.fPrint(ERROR, "- You must provide an Instruction Set Architecture.");
          oConsole.fCleanup();
          os._exit(2);
        if sValue not in ["x86", "x64"]:
          oConsole.fPrint(ERROR, "- Unknown Instruction Set Architecture ", repr(sValue));
          oConsole.fCleanup();
          os._exit(2);
        sApplicationISA = sValue;
      elif sSettingName in ["quiet", "silent"]:
        if sValue is None or sValue.lower() == "true":
          gbQuiet = True;
        elif sValue.lower() == "false":
          gbQuiet = False;
        else:
          oConsole.fPrint(ERROR, "- The value for ", ERROR_INFO, "--", sSettingName, ERROR, \
              " must be \"true\" or \"false\".");
      elif sSettingName in ["verbose", "debug"]:
        if sValue is None or sValue.lower() == "true":
          gbVerbose = True;
        elif sValue.lower() == "false":
          gbVerbose = False;
        else:
          oConsole.fPrint(ERROR, "- The value for ", ERROR_INFO, "--", sSettingName, ERROR, \
              " must be \"true\" or \"false\".");
      elif sSettingName in ["fast", "quick"]:
        if sValue is None or sValue.lower() == "true":
          bFast = True;
        elif sValue.lower() == "false":
          bFast = False;
        else:
          oConsole.fPrint(ERROR, "- The value for ", ERROR_INFO, "--", sSettingName, ERROR, \
              " must be \"true\" or \"false\".");
      elif sSettingName in ["forever"]:
        if sValue is None or sValue.lower() == "true":
          bRepeat = True;
        elif sValue.lower() == "false":
          bRepeat = False;
        else:
          oConsole.fPrint(ERROR, "- The value for ", ERROR_INFO, "--", sSettingName, ERROR, \
              " must be \"true\" or \"false\".");
      elif sSettingName in ["repeat"]:
        bRepeat = sValue is None or sValue.lower() != "false";
        if bRepeat and sValue is not None:
          try:
            uNumberOfRepeats = long(sValue);
            if uNumberOfRepeats < 2:
              uNumberOfRepeats = None;
            elif str(uNumberOfRepeats) != sValue:
              uNumberOfRepeats = None;
          except:
            pass;
          if uNumberOfRepeats is None:
            oConsole.fPrint(ERROR, "- The value for ", ERROR_INFO, "--", sSettingName, ERROR, \
                " must be an integer larger than 1 or \"false\".");
      elif sSettingName in ["collateral"]:
        if sValue is None:
          guMaximumNumberOfBugs = guDefaultCollateralMaximumNumberOfBugs;
        else:
          # -- collateral=1 means one collateral bug in addition to the first bug.
          guMaximumNumberOfBugs = long(sValue) + 1;
      elif sSettingName in ["symbols"]:
        if sValue is None or not mFileSystem.fbIsFolder(sValue):
          oConsole.fPrint(ERROR, "- The value for ", ERROR_INFO, "--", sSettingName, ERROR, \
              " must be a valid path.");
        asAdditionalLocalSymbolPaths.append(sValue);
      elif sSettingName in ["test-internal-error", "internal-error-test"]:
        raise Exception("Testing internal error");
      else:
        if not sValue:
          oConsole.fPrint(ERROR, "- You cannot provide an argument (", ERROR_INFO, "--", sSettingName, ERROR, \
              ") without a value.");
          oConsole.fCleanup();
          os._exit(2);
        try:
          xValue = json.loads(sValue);
        except ValueError as oError:
          oConsole.fPrint(ERROR, "- Cannot decode argument JSON value ", ERROR_INFO, "--", sSettingName, "=", sValue, \
              ERROR, ": ", ERROR_INFO, " ".join(oError.args), ERROR, ".");
          oConsole.fCleanup();
          os._exit(2);
        # User provided config settings must be applied after any keyword specific config settings:
        dxUserProvidedConfigSettings[sSettingName] = xValue;
    elif sArgument in ddxApplicationSettings_by_sKeyword:
      if sApplicationKeyword is not None:
        oConsole.fPrint(ERROR, "- You cannot provide multiple application keywords.");
        oConsole.fCleanup();
        os._exit(2);
      sApplicationKeyword = sArgument;
    elif sArgument[-1] == "?":
      sApplicationKeyword = sArgument[:-1];
      dxApplicationSettings = ddxApplicationSettings_by_sKeyword.get(sApplicationKeyword);
      if not dxApplicationSettings:
        oConsole.fPrint(ERROR, "- Unknown application keyword ", ERROR_INFO, sApplicationKeyword, ERROR, ".");
        oConsole.fCleanup();
        os._exit(2);
      fPrintApplicationKeyWordHelp(sApplicationKeyword, dxApplicationSettings);
      oConsole.fCleanup();
      os._exit(0);
    else:
      if sApplicationBinaryPath is not None:
        oConsole.fLock();
        try:
          oConsole.fPrint(ERROR, "- You cannot provide multiple application binaries.");
          oConsole.fPrint(ERROR, "  (Did you perhaps forget to put ", ERROR_INFO, "--", ERROR, \
              " before the start of the application arguments?)");
        finally:
          oConsole.fUnlock();
        oConsole.fCleanup();
        os._exit(2);
      if len(auApplicationProcessIds) > 0:
        oConsole.fPrint(ERROR, "- You cannot provide process ids and an application binary.");
        oConsole.fCleanup();
        os._exit(2);
      if sUWPApplicationPackageName is not None:
        oConsole.fPrint(ERROR, "- You cannot provide an application UWP package name and a binary.");
        oConsole.fCleanup();
        os._exit(2);
      sApplicationBinaryPath = sArgument;
  
  if bFast:
    gbQuiet = True;
    dxUserProvidedConfigSettings["bGenerateReportHTML"] = False;
    dxUserProvidedConfigSettings["asSymbolServerURLs"] = [];
    dxUserProvidedConfigSettings["cBugId.bUse_NT_SYMBOL_PATH"] = False;
  
  dsApplicationURLTemplate_by_srSourceFilePath = {};
  
  fSetup = None; # Function specific to a keyword application, used to setup stuff before running.
  fCleanup = None; # Function specific to a keyword application, used to cleanup stuff before & after running.
  if sApplicationKeyword:
    dxApplicationSettings = ddxApplicationSettings_by_sKeyword.get(sApplicationKeyword);
    if not dxApplicationSettings:
      oConsole.fPrint(ERROR, "- Unknown application keyword ", ERROR_INFO, sApplicationKeyword, ERROR, ".");
      oConsole.fCleanup();
      os._exit(2);
    fSetup = dxApplicationSettings.get("fSetup");
    fCleanup = dxConfig["bCleanup"] and dxApplicationSettings.get("fCleanup");
    # Get application binary/UWP package name/process ids as needed:
    if "sBinaryPath" in dxApplicationSettings:
      # This application is started from the command-line.
      if auApplicationProcessIds:
        oConsole.fPrint(ERROR, "- You cannot provide process ids for application keyword ", ERROR_INFO, \
            sApplicationKeyword, ERROR, ".");
        oConsole.fCleanup();
        os._exit(2);
      if sUWPApplicationPackageName:
        oConsole.fPrint(ERROR, "- You cannot provide an application UWP package name for application keyword ", \
            ERROR_INFO, sApplicationKeyword, ERROR, ".");
        oConsole.fCleanup();
        os._exit(2);
      if sApplicationBinaryPath is None:
        sApplicationBinaryPath = dxApplicationSettings["sBinaryPath"];
        if sApplicationBinaryPath is None:
          oConsole.fPrint(ERROR, "- The main application binary for ", ERROR_INFO, sApplicationKeyword, \
              ERROR, " could not be detected on your system.");
          oConsole.fPrint(ERROR, "  Please provide the path to this binary in the arguments.");
          oConsole.fCleanup();
          os._exit(4);
    elif "dxUWPApplication" in dxApplicationSettings:
      dxUWPApplication = dxApplicationSettings["dxUWPApplication"];
      # This application is started as a Universal Windows Platform application.
      if sApplicationBinaryPath:
        oConsole.fPrint(ERROR, "- You cannot provide an application binary for application keyword ", \
            ERROR_INFO, sApplicationKeyword, ERROR, ".");
        oConsole.fCleanup();
        os._exit(2);
      if auApplicationProcessIds:
        oConsole.fPrint(ERROR, "- You cannot provide process ids for application keyword ", ERROR_INFO, \
            sApplicationKeyword, ERROR, ".");
        oConsole.fCleanup();
        os._exit(2);
      sUWPApplicationPackageName = dxUWPApplication["sPackageName"];
      sUWPApplicationId = dxUWPApplication["sId"];
    elif not auApplicationProcessIds:
      # This application is attached to.
      oConsole.fPrint(ERROR, "- You must provide process ids for application keyword ", \
          ERROR_INFO, sApplicationKeyword, ERROR, ".");
      oConsole.fCleanup();
      os._exit(2);
    elif asApplicationOptionalArguments:
      # Cannot provide arguments if we're attaching to processes
      oConsole.fPrint(ERROR, "- You cannot provide arguments for application keyword ", \
          ERROR_INFO, sApplicationKeyword, ERROR, ".");
      oConsole.fCleanup();
      os._exit(2);
    if "asApplicationAttachToProcessesForExecutableNames" in dxApplicationSettings:
      gasAttachToProcessesForExecutableNames = dxApplicationSettings["asApplicationAttachToProcessesForExecutableNames"];
    # Get application arguments;
    if "fasGetStaticArguments" in dxApplicationSettings:
      fasGetApplicationStaticArguments = dxApplicationSettings["fasGetStaticArguments"];
      asApplicationStaticArguments = fasGetApplicationStaticArguments(bForHelp = False);
    else:
      asApplicationStaticArguments = [];
    if asApplicationOptionalArguments is None and "fasGetOptionalArguments" in dxApplicationSettings:
      fasGetApplicationOptionalArguments = dxApplicationSettings["fasGetOptionalArguments"];
      asApplicationOptionalArguments = fasGetApplicationOptionalArguments(bForHelp = False);
    asApplicationArguments = asApplicationStaticArguments + asApplicationOptionalArguments;
    # Apply application specific settings
    if dxApplicationSettings.get("dxConfigSettings"):
      dxApplicationConfigSettings = dxApplicationSettings["dxConfigSettings"];
      if gbVerbose:
        oConsole.fPrint("* Applying application specific configuration for %s:" % sApplicationKeyword);
      for (sSettingName, xValue) in dxApplicationConfigSettings.items():
        if sSettingName not in dxUserProvidedConfigSettings:
          # Apply and show result indented or errors.
          if not fbApplyConfigSetting(sSettingName, xValue, [None, "  "][gbVerbose]):
            os._exit(2);
      if gbVerbose:
        oConsole.fPrint();
    # Apply application specific source settings
    if "dsURLTemplate_by_srSourceFilePath" in dxApplicationSettings:
      dsApplicationURLTemplate_by_srSourceFilePath = dxApplicationSettings["dsURLTemplate_by_srSourceFilePath"];
    # If not ISA is specified, apply the application specific ISA (if any).
    if not sApplicationISA and "sISA" in dxApplicationSettings:
      sApplicationISA = dxApplicationSettings["sISA"];
    if "asBinaryNamesThatAreAllowedToRunWithoutPageHeap" in dxApplicationSettings:
      gasBinaryNamesThatAreAllowedToRunWithoutPageHeap += [
        sBinaryName.lower() for sBinaryName in dxApplicationSettings["asBinaryNamesThatAreAllowedToRunWithoutPageHeap"]
      ];
  elif (auApplicationProcessIds or sUWPApplicationPackageName or sApplicationBinaryPath):
    # There are no static arguments if there is no application keyword, only the user-supplied optional arguments
    # are used if they are supplied:
    asApplicationArguments = asApplicationOptionalArguments or [];
  else:
    oConsole.fLock();
    try:
      oConsole.fPrint(ERROR, "- You must provide something to debug. This can be either one or more process");
      oConsole.fPrint(ERROR, "  ids, an application command-line or an UWP application package name.");
      oConsole.fPrint("Run \"", INFO, "BugId -h", NORMAL, "\" for help on command-line arguments.");
    finally:
      oConsole.fUnlock();
    oConsole.fCleanup();
    os._exit(2);
  
  # Apply user provided settings:
  for (sSettingName, xValue) in dxUserProvidedConfigSettings.items():
    # Apply and show result or errors:
    if not fbApplyConfigSetting(sSettingName, xValue, [None, ""][gbVerbose]):
      os._exit(2);

  # Check license
  if not 'cracked':
    (asLicenseErrors, asLicenseWarnings) = mProductDetails.ftasGetLicenseErrorsAndWarnings();
    if asLicenseErrors:
      oConsole.fLock();
      try:
        oConsole.fPrint(ERROR, u"\u250C\u2500", ERROR_INFO, " Software license error ", ERROR, sPadding = u"\u2500");
        for sLicenseError in asLicenseErrors:
          oConsole.fPrint(ERROR, u"\u2502 ", ERROR_INFO, sLicenseError);
        oConsole.fPrint(ERROR, u"\u2514", sPadding = u"\u2500");
      finally:
        oConsole.fUnlock();
      os._exit(5);
    if asLicenseWarnings:
      oConsole.fLock();
      try:
        oConsole.fPrint(WARNING, u"\u250C\u2500", WARNING_INFO, " Software license warning ", WARNING, sPadding = u"\u2500");
        for sLicenseWarning in asLicenseWarnings:
          oConsole.fPrint(WARNING, u"\u2502 ", WARNING_INFO, sLicenseWarning);
        oConsole.fPrint(WARNING, u"\u2514", sPadding = u"\u2500");
      finally:
        oConsole.fUnlock();
  
  if bRepeat:
    sValidStatisticsFileName = mFileSystem.fsValidName("Reproduction statistics.txt");
  uRunCounter = 0;
  while 1: # Will only loop if bRepeat is True
    nStartTime = time.clock();
    if fSetup:
      # Call setup before the application is started. Argument is boolean value indicating if this is the first time
      # the function is being called.
      oConsole.fStatus("* Applying special application configuration settings...");
      fSetup(bFirstRun = uRunCounter == 0);
    uRunCounter += 1;
    oConsole.fLock();
    try:
      if sApplicationBinaryPath:
        # make the binary path absolute because relative paths don't work.
        sApplicationBinaryPath = os.path.abspath(sApplicationBinaryPath);
        if not gbQuiet:
          asCommandLine = [sApplicationBinaryPath] + asApplicationArguments;
          oConsole.fPrint("* Command line: ", INFO, " ".join(asCommandLine));
        oConsole.fStatus("* The debugger is starting the application...");
      else:
        if auApplicationProcessIds:
          asProcessIdsOutput = [];
          for uApplicationProcessId in auApplicationProcessIds:
            if asProcessIdsOutput: asProcessIdsOutput.append(", ");
            asProcessIdsOutput.extend([INFO, str(uApplicationProcessId), NORMAL]);
          oConsole.fPrint("* Running process ids: ", INFO, *asProcessIdsOutput);
        if sUWPApplicationPackageName:
          if not gbQuiet:
            if asApplicationArguments:
              oConsole.fPrint("* UWP application id: ", INFO, sUWPApplicationId, NORMAL, ", package name: ", INFO, \
                  sUWPApplicationPackageName, NORMAL, ", Arguments: ", INFO, " ".join(asApplicationArguments));
            else:
              oConsole.fPrint("* UWP application id: ", INFO, sUWPApplicationId, NORMAL, ", package name: ", INFO, \
                  sUWPApplicationPackageName);
        if not sUWPApplicationPackageName:
          oConsole.fStatus("* The debugger is attaching to running processes of the application...");
        elif auApplicationProcessIds:
          oConsole.fStatus("* The debugger is attaching to running processes and starting the application...");
        else:
          oConsole.fStatus("* The debugger is starting the application...");
    finally:
      oConsole.fUnlock();
    asLocalSymbolPaths = dxConfig["asLocalSymbolPaths"] or [];
    if asAdditionalLocalSymbolPaths:
      asLocalSymbolPaths += asAdditionalLocalSymbolPaths;
    oBugId = cBugId(
      sCdbISA = sApplicationISA or cBugId.sOSISA,
      sApplicationBinaryPath = sApplicationBinaryPath or None,
      auApplicationProcessIds = auApplicationProcessIds or None,
      sUWPApplicationPackageName = sUWPApplicationPackageName or None,
      sUWPApplicationId = sUWPApplicationId or None,
      asApplicationArguments = asApplicationArguments,
      asLocalSymbolPaths = asLocalSymbolPaths or None,
      asSymbolCachePaths = dxConfig["asSymbolCachePaths"], 
      asSymbolServerURLs = dxConfig["asSymbolServerURLs"],
      dsURLTemplate_by_srSourceFilePath = dsApplicationURLTemplate_by_srSourceFilePath,
      bGenerateReportHTML = dxConfig["bGenerateReportHTML"],
      uProcessMaxMemoryUse = dxConfig["uProcessMaxMemoryUse"],
      uTotalMaxMemoryUse = dxConfig["uTotalMaxMemoryUse"],
      uMaximumNumberOfBugs = guMaximumNumberOfBugs,
    );
    oBugId.fAddEventCallback("Application resumed", fApplicationResumedCallback);
    oBugId.fAddEventCallback("Application running", fApplicationRunningCallback);
    oBugId.fAddEventCallback("Application suspended", fApplicationSuspendedCallback);
    oBugId.fAddEventCallback("Application debug output", fApplicationDebugOutputCallback);
    oBugId.fAddEventCallback("Application stderr output", fApplicationStdErrOutputCallback);
    oBugId.fAddEventCallback("Application stdout output", fApplicationStdOutOutputCallback);
    oBugId.fAddEventCallback("Bug report", fBugReportCallback);
    oBugId.fAddEventCallback("Cdb stderr output", fCdbStdErrOutputCallback);
    if gbVerbose:
      oBugId.fAddEventCallback("Cdb stdin input", fCdbStdInInputCallback);
      oBugId.fAddEventCallback("Cdb stdout output", fCdbStdOutOutputCallback);
      oBugId.fAddEventCallback("Log message", fLogMessageCallback);
    oBugId.fAddEventCallback("Failed to apply application memory limits", fFailedToApplyApplicationMemoryLimitsCallback);
    oBugId.fAddEventCallback("Failed to apply process memory limits", fFailedToApplyProcessMemoryLimitsCallback);
    oBugId.fAddEventCallback("Failed to debug application", fFailedToDebugApplicationCallback);
    oBugId.fAddEventCallback("Internal exception", fInternalExceptionCallback);
    if not 'cracked':
      oBugId.fAddEventCallback("License warnings", fLicenseWarningsCallback);
      oBugId.fAddEventCallback("License errors", fLicenseErrorsCallback);
    oBugId.fAddEventCallback("Page heap not enabled", fPageHeapNotEnabledCallback);
    oBugId.fAddEventCallback("Process attached", fProcessAttachedCallback);
    oBugId.fAddEventCallback("Process started", fProcessStartedCallback);
    oBugId.fAddEventCallback("Process terminated", fProcessTerminatedCallback);

    if dxConfig["nApplicationMaxRunTime"] is not None:
      oBugId.foSetTimeout("Maximum application runtime", dxConfig["nApplicationMaxRunTime"], \
          fApplicationMaxRunTimeCallback);
    if dxConfig["bExcessiveCPUUsageCheckEnabled"] and dxConfig["nExcessiveCPUUsageCheckInitialTimeout"]:
      oBugId.fSetCheckForExcessiveCPUUsageTimeout(dxConfig["nExcessiveCPUUsageCheckInitialTimeout"]);
    guDetectedBugsCount = 0;
    oBugId.fStart();
    oBugId.fWait();
    if gbAnErrorOccured:
      if fCleanup:
        # Call cleanup after runnning the application, before exiting BugId
        oConsole.fStatus("* Cleaning up application state...");
        fCleanup();
      oConsole.fCleanup();
      os._exit(3);
    if guDetectedBugsCount == 0:
      oConsole.fPrint(u"\u2500\u2500 The application terminated without a bug being detected ", sPadding = u"\u2500");
      gduNumberOfRepros_by_sBugIdAndLocation.setdefault("No crash", 0);
      gduNumberOfRepros_by_sBugIdAndLocation["No crash"] += 1;
    if gbVerbose:
      oConsole.fPrint("  Application time: %s seconds" % (long(oBugId.fnApplicationRunTime() * 1000) / 1000.0));
      nOverheadTime = time.clock() - nStartTime - oBugId.fnApplicationRunTime();
      oConsole.fPrint("  BugId overhead:   %s seconds" % (long(nOverheadTime * 1000) / 1000.0));
    if uNumberOfRepeats is not None:
      uNumberOfRepeats -= 1;
      if uNumberOfRepeats == 0:
        bRepeat = False;
    if not bRepeat:
      if fCleanup:
        # Call cleanup after runnning the application, before exiting BugId
        oConsole.fStatus("* Cleaning up application state...");
        fCleanup();
      oConsole.fCleanup();
      os._exit(guDetectedBugsCount > 0 and 1 or 0);
    sStatistics = "";
    auOrderedNumberOfRepros = sorted(list(set(gduNumberOfRepros_by_sBugIdAndLocation.values())));
    auOrderedNumberOfRepros.reverse();
    for uNumberOfRepros in auOrderedNumberOfRepros:
      for sBugIdAndLocation in gduNumberOfRepros_by_sBugIdAndLocation.keys():
        if gduNumberOfRepros_by_sBugIdAndLocation[sBugIdAndLocation] == uNumberOfRepros:
          sStatistics += "%d \xD7 %s (%d%%)\r\n" % (uNumberOfRepros, str(sBugIdAndLocation), \
              round(100.0 * uNumberOfRepros / uRunCounter));
    if dxConfig["sReportFolderPath"] is not None:
      sStatisticsFilePath = mFileSystem.fsPath(dxConfig["sReportFolderPath"], sValidStatisticsFileName);
    else:
      sStatisticsFilePath = mFileSystem.fsPath(sValidStatisticsFileName);
    eWriteDataToFileResult = mFileSystem.feWriteDataToFile(
      sStatistics,
      sStatisticsFilePath,
      fbRetryOnFailure = lambda: False,
    );
    if eWriteDataToFileResult:
      oConsole.fPrint("  Statistics:       ", ERROR, "Cannot be saved (", ERROR_INFO, repr(eWriteDataToFileResult), \
          ERROR, ")");
    else:
      oConsole.fPrint("  Statistics:       ", INFO, sStatisticsFilePath, NORMAL, " (%d bytes)" % len(sStatistics));
    oConsole.fPrint(); # and loop
  raise AssertionError("Not reached!");
  
if __name__ == "__main__":
  # Apply settings in dxConfig["cBugId"] to cBugId.dxConfig, then replace dxConfig["cBugId"] with cBugId.dxConfig.
  for (sName, xValue) in dxConfig["cBugId"].items():
    # Note that this does not allow modifying individual properties of dictionaries in dxConfig for cBugId.
    # But at this time, there are no dictionaries in dxConfig, so this is not required.
    cBugId.dxConfig[sName] = xValue;
  dxConfig["cBugId"] = cBugId.dxConfig;
  try:
    fMain(sys.argv[1:]);
  except Exception as oException:
    cException, oException, oTraceBack = sys.exc_info();
    fPrintExceptionInformation(oException, oTraceBack);
    oConsole.fCleanup();
    os._exit(3);
