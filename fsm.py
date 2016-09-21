'''
Created on 15 set 2016

@author: damiano
'''

import epics
import threading


#classe che rappresenta un ingresso per le macchine a stati

class fsmIO(object):
    def __init__(self, name):
        self._name = name
        self.conn = False #pv connessa
        self.val = None
        self.data = {}    # pv data
        self._attached = set() # set che contiene le macchine a stati che utilizzano questo ingresso
        self._pv = epics.PV(name, callback=self.chgcb, connection_callback=self.concb, auto_monitor=True)
        self._lck = threading.Lock() 
    
    def attach(self, obj):
        self._attached.add(obj)
    
    #callback connessione    
    def concb(self, **args):
        self.lock()
        self._lock()
        self.conn = args.get('conn', False)
        self.trigger()
        self._unlock()        
        self.unlock()
    
    #callback aggiornamento
    def chgcb(self, **args):
        self.lock()
        self._lock()
        self.data = args
        self.val=args.get('value', None)
        self.trigger()
        self._unlock()        
        self.unlock()
    
    #put callback
    def putcb(self, name):
        self.lock()
        self._lock()
        self.trigger()
        self._unlock()        
        self.unlock()
    	pass

    # "sveglia" le macchine a stati connesse a questo ingresso    
    def trigger(self):
        for o in self._attached:
            o.trigger(self._name)

    # ottiene l'accesso esclusivo alle mmacchine a stati connesse a questo 
    # ingresso
    def _lock(self):
        for o in self._attached:
            o.lock()
        
    def _unlock(self):
        for o in self._attached:
            o.unlock()

    #ottiene l'accesso esclusivo a questo ingresso
    def lock(self):
        self._lck.acquire()

    def unlock(self):
        self._lck.release()
        
    def put(self, value):
    	self._pv.put(value, callback=self.putcb, use_complete=True)
        

#rappresenta una lista di oggetti input
class fsmIOs(object):

    def __init__(self):
        self._ios = {}
        self._lck = threading.Lock()
    
    # connette (crea se non esistono) gli ingressi names all'oggetto obj
    def link(self, names, obj):
        ret = {}
        for name in names:
            if name not in self._ios:
                self._ios[name] = fsmIO(name)
            self._ios[name].attach(obj)
            ret[name] = self._ios[name]
        return ret

    def get(self, name):
        return self._ios[name]            
    
    # ottiene l'accesso esclusivo a questo oggetto            
    def lock(self):
        self._lck.acquire()
    
    def unlock(self):
        self._lck.release()

    def getFsmIO(self, fsm):
    	ret = {}
    	for io in self._ios:
    		if fsm in io._attached:
    			ret[io._name] = io
    	return ret
    




# classe base per la macchina a stati
class fsmBase(object):
    def __init__(self, ios, stateDefs):
        
        # stateDefs e un dizionario in cui la chiave e il nome dello stato e
        # il valore un array di ingressi utilizzati dallo stato
        self._ios = io
        self._states = {}
        self._ios.lock()
        for stateDef in stateDefs:
            self._states[stateDef] = self._ios.link(stateDefs[stateDef], self)
        self._ios.unlock()
        self._curstate = None
        self._curexit = None
        self._nextstate = None
        self._nextentry = None
        self._nextexit = None
        self._cursens = {}
        self._cond = threading.Condition()
    	self._myios = self._ios.getFsmIO(self)


    # ottiene accesso esclusivo a questo oggetto        
    def lock(self):
        self._cond.acquire()

    def unlock(self):
        self._cond.release()

    #cambia stato
    def gotoState(self, state):
        self._nextstatename = state
        #metodo eval del prossimo stato
        self._nextstate = getattr(self, '%s_eval' % state)
        #metodo entry del prossimo stato 
        self._nextentry = getattr(self, '%s_entry' % state, None)
        #metodo exit del prossimo stato
        self._nextexit = getattr(self, '%s_exit' % state, None)

    #valuta la macchina a stati nello stato corrente
    def eval(self):
        again = True
        while again: 
            if self._nextstate != self._curstate:
                if self._nextentry:
                    self._nextentry()
                self._curstate = self._nextstate
                self._curexit = self._nextexit
                self._cursens = self._states[self._nextstatename]
            
            self.commonEval()                
            self._curstate()        
            if self._nextstate != self._curstate:
                again = True
                if self._curexit:
                    self._curexit()
                self.commonExit()
            else:
                again = False        
    
    # valuta all'infinito la macchina a stati
    def eval_forever(self):
        self.lock()
        while(1):
            print "-------------------"
            self.eval() # eval viene eseguito con l'accesso esclusivo su questa macchina
            self._cond.wait() # la macchina va in sleep in attesa di un evento (da un ingresso)

            
    def input(self, name):
        return self._ios.get(name)       

    #chiamata dagli ingressi quando arrivano eventi
    def trigger(self, name):
        if name in self._cursens:
            self._cond.notify() #sveglia la macchina solo se quell'ingresso e' nella sensitivity list dello stato corrente

    def commonEval(self):
        pass

    def commonExit(self):
    	pass


################################################################################

# ESEMPIO DI UTILIZZO
            
class zeroFreqFsm(fsmBase):
    def __init__(self, ios, statesWithPvs):
        fsmBase.__init__(self, inputs, outputs, statesWithPvs)
        self.freqErr = self.input("freqErr")
        self.enable = self.input("zeroEn")
        self.movn = self.input("m1:motor.MOVN")
        self.position = self.input("m1:motor")
        self.moveRel = self.input("m1:moveRel")
        self.limitSwitch1 = 0
        self.limitSwitch2 = 0
        self.progress = 0  #to report progress of the procedure [0-100]
        self.gotoState('init')

        #info to be passed to fsm
        self.maxFreqDelta = 100;
        self.microstep = 64
        self.bigStep = microstep*20
        self.smallStep = microstep*2
        self.maxSteps = microstep*1500
        self.maxStepsDelta = maxFreqDelta*smallStep

        #auxiliary variables
        self.lastmovn = movn.val
        self.freqErr0 = freqErr.val
        self.stepsDone = 0
        self.foundDirection = 0

    def commonEval(self):
        #check all connections useful to the current state
        if enable.val != 1:
        	self.gotoState("stop") 
        for io in self._cursens:
        	if not io.conn:
        		self.gotoState("error")

    def commonExit(self):
    	#write current state name, current operation and progress to pv
    	self.progress += 1 #TODO
    	self.reportState = self._nextstatename
       
    def init_eval(self):
        print "------->Boot up zeroFreq finite state machine"
        self.gotoState('idle')
    
    def idle_entry(self):
        print "boot-up complete, entering idle..."
        
    def idle_eval(self):
        print "evaluating idle"
        if enable.val == 1:
            if freqErr.val <= 1:
            	self.gotoState("end")
            elif 1<freqErr.val<=250:
            	self.gotoState("badRange")
            elif 250<freqErr.val<10e3:
            	self.gotoState("inRange")
            else:
            	self.gotoState("outRange")

    #move down of 1000 steps to exit badRange
    def badRange_entry(self):
    	if movn.val == 0			
			moveRel.put(-1000 * microstep)
		lastmovn = movn.val

	#check if successfully exited the bad range when end of movement
    def badRange_eval(self):
    	if movn.val < lastmovn:
    		if 250<freqErr.val<10e3:
    			self.gotoState("inRange")
    		else:
    			gotoState("error")

    #move down and save initial freqErr
    def inRange_entry(self):
    	freqErr0 = freqErr.val
    	if movn.val == 0
    		numSteps = bigStep if freqErr.val>250 else smallStep
    		moveRel.put(-numSteps)
    		stepsDone = numSteps
    	lastmovn = movn.val

    #move until i exit the delta, where freq is not correlable to movement
    def inRange_eval(self):
    	if movn.val < lastmovn:
    		if abs(freqErr.val-freqErr0)>maxFreqDelta*1.1:  #out of delta i assume the freqerr is safe
    			self.gotoState("minimize")
    			foundDirection = -1 if freqErr.val < freqErr0 else 1
    		elif freqErr.val >= 10e3 or limitSwitch1.val or limitSwitch2.val  #did not surpassed delta
    			self.gotoState("tryUp")
    		elif stepsDone > maxStepsDelta*1.5:  #stall
    			self.gotoState("error")
    		else:
    			numSteps = bigStep if freqErr.val>250 else smallStep
    			moveRel.put(-numSteps)
    			stepsDone = numSteps
    	lastmovn = movn.val

    #move fast until enter the <10k range
    def outRange_entry(self):
    	if movn.val == 0
    		moveRel.put(-bigStep)
    		stepsDone = bigStep
    	lastmovn = movn.val

    #continue moving
    def outRange_eval(self):
    	if movn.val < lastmovn:
    		if freqErr.val < 10e3-maxFreqDelta*1.3:   #out of delta and inside 10k
    			self.gotoState("minimize")
    			foundDirection = -1
    		elif limitSwitch2.val or limitSwitch2.val:  #limit switch
    			self.gotoState("tryUp")
    		elif stepsDone > maxSteps*1.1:			#stall
    			self.gotoState("error")
    		else:								#continue moving
    			moveRel.put(-bigStep)
    			stepsDone += bigStep
    	lastmovn = movn.val

    def tryUp_entry(self):
    	freqErr0 = freqErr.val
    	if movn.val == 0
    		numSteps = bigStep if freqErr.val>250 else smallStep
    		moveRel.put(numSteps)
    		stepsDone = numSteps
    	lastmovn = movn.val

    def tryUp_eval(self):
    	if movn.val < lastmovn:
    		if abs(freqErr.val-freqErr0)>maxFreqDelta*1.1:
    			self.gotoState("minimize")
    			foundDirection = 1 if freqErr.val < freqErr0 else -1
    		elif limitSwitch1.val or limitSwitch2.val:
    			self.gotoState("error")
    		elif freqErr0>=10e3 and stepsDone>=maxSteps*1.1:
    			self.gotoState("error")
    		elif freqErr0<10e3 and stepsDone>=maxStepsDelta*1.5:
    			self.gotoState("error")
    		else:
    			numSteps = bigStep if freqErr.val>250 else smallStep
    			moveRel.put(numSteps)
    			stepsDone = numSteps
    	lastmovn = movn.val

    def minimize_entry(self):
    	freqErr0 = freqErr.val
    	lastmovn = 1

    def minimize_eval(self):
    	if movn.val < lastmovn:
    		if stepsDone > maxStepsDelta && freqErr.val>freqErr0*1.3:
    			gotoState("error")
    		elif freqErr.val > 100:
    			numSteps = (freqErr.val - 50) * smallStep
    			moveRel.put(numSteps*foundDirection)
    		elif freqErr.val > 20
    			numSteps = (freqErr.val - 10) * smallStep
    			moveRel.put(numSteps*foundDirection)
    		elif freqErr.val > 10
    			moveRel.put(smallStep*foundDirection)
    		elif freqErr > 1
    			moveRel.put(microstep*foundDirection)
    		else:
    			self.gotoState("end")
    	lastmovn = movn.val
    
    def end_eval(self):
        print "evaluating end"
        enable.put(0);
        self.gotoState("idle")
    
    def error_eval(self):
        print "evaluating error"
        enable.put(0);
        self.gotoState("idle")            
        
        
ios = fsmIOs()

statesWithPvs = {
    "init" : [],
    "idle" : ["zeroEn"],
    "outRng_goLow" : ["zeroEn","m1:motor", "freqErr", "m1:motor.MOVN", "m1:moveRel"],
    "outRng_gohigh" : ["zeroEn","m1:motor", "freqErr", "m1:motor.MOVN", "m1:moveRel"],
    "inRng_golow" : ["zeroEn","m1:motor", "freqErr", "m1:motor.MOVN", "m1:moveRel"],
    "inRng_goHigh" : ["zeroEn","m1:motor", "freqErr", "m1:motor.MOVN", "m1:moveRel"],
    "minimize" : ["zeroEn","m1:motor", "freqErr", "m1:motor.MOVN", "m1:moveRel"],
    "end" : ["zeroEn","m1:motor", "freqErr", "m1:motor.MOVN", "m1:moveRel"],
    "error" : ["zeroEn","m1:motor", "freqErr", "m1:motor.MOVN", "m1:moveRel"]
}



f = zeroFreqFsm(ios, statesWithPvs)

f.eval_forever()        
