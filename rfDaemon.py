#! /usr/bin/python

from threading import Thread, enumerate
import signal
from time import sleep
import argparse

from waves import waves
from caraterize import caraterize
from pulseRf import pulseRf
from zeroFreq import zeroFreq
from softTuner import softTuner
from reporter import reporter
from store import store
from fsm import fsmTimers, cavityPVs, fsmLoggerToFile

class fsmThread(Thread):
    def __init__(self, fsm):
        Thread.__init__(self)
        self.fsm = fsm

    def run(self):
        print("Starting fsm: %s " % self.fsm.fsmname())
        try:
            self.fsm.eval_forever()
        except Exception, e:
            print(repr(e)) 
        print("Stopped fsm: %s " % self.fsm.fsmname())

def main():
    parser = argparse.ArgumentParser(description="rfDaemon - loads the required fsm to perform procedures")
    parser.add_argument("configFile", help="the path of the configuration file", type=str)
    parser.add_argument("-v", "--verbosity", help="set the debug level", default=2, type=int)
    args = parser.parse_args()
    
    file = open(args.configFile, "r")
    lines = file.readlines()
    file.close()

    targets = {}
    for line in lines:
        if line.startswith("#"):
            continue
        columns=line.split('=')
        cryostat = int(columns[0])
        cavitiesStr = columns[1].split(",")
        cavities = []
        for cavity in cavitiesStr:
            cavities.append(int(cavity))
        targets[cryostat]=cavities

    #create a thread for the timer manager
    timerManager = fsmTimers()
    commonIos = cavityPVs()
    commonLogger = fsmLoggerToFile(args.verbosity)
    #timerManager.start()  #will be done automatically from first fsm loaded

    #a dictitonary containing fsm objects as keys and their thread (or None) as values
    fsms = {}
    for cryostat, cavities in targets.iteritems():
        for cavity in cavities:
            name = "Cr%02d.%1d-" % (cryostat, cavity)
            w = waves(name+"WAVE", cryostat, cavity, tmgr=timerManager, ios=commonIos, logger=commonLogger)
            c = caraterize(name+"CARA", cryostat, cavity, tmgr=timerManager, ios=commonIos, logger=commonLogger)
            z = zeroFreq(name+"ZRFR", cryostat, cavity, tmgr=timerManager, ios=commonIos, logger=commonLogger)
            p = pulseRf(name+"PULS", cryostat, cavity, tmgr=timerManager, ios=commonIos, logger=commonLogger)
            s = softTuner(name+"SWTU", cryostat, cavity, tmgr=timerManager, ios=commonIos, logger=commonLogger)
            fsms.update({w:None, c:None, z:None, p:None, s:None})


    for fsm in fsms.iterkeys():
        newThread = fsmThread(fsm)
        newThread.start()
        fsms[fsm]=newThread
    print("All fsms started!")

    #start another fsm to report if all the others are alive to epics db
    repo = reporter("REPORT", fsms, tmgr=timerManager, ios=commonIos, logger=commonLogger)
    repoThread = fsmThread(repo)
    repoThread.start()

    stor = store("STORE", tmgr=timerManager, ios=commonIos)
    storThread = fsmThread(stor)
    storThread.start()

    #sleep(0.1)
    #for i in enumerate():
    #   print(i)
    #print targets
    #for i in fsms:
    #   print i

    def killAll(signum, frame):
        print("Signal: %d -> Going to kill all fsms" % signum)
        for fsm, thread in fsms.iteritems():
            if thread.isAlive():
                fsm.kill()
                thread.join()
        print("Killed all the fsms")
        if repoThread.isAlive():  
            repo.kill()
            repoThread.join()
        print("Killed the reporter thread")
        if storThread.isAlive():  
            stor.kill()
            storThread.join()
        print("Killed the store thread")
        if timerManager.isAlive():  #if no fsm is loaded it won't be alive
            timerManager.kill()
        print("Killed the timer manager")
        
    
    signal.signal(signal.SIGINT, killAll)
    signal.pause()


if __name__ == '__main__':        
    main()