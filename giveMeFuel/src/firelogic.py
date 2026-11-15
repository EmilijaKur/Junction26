import time
from collections import deque

CONF_THRESHOLD = 0.5 #if coefficient is below 50% we ignore the fire as backround noise
GROWTH_FACTOR = 1.2 #if the fire grew by 20% we consider it growing
RISE_LIMIT = 10.0 #raise by 10 degrees is considered dangerous
DURATION_LIMIT = 30.0 # a fire that has been there for more than 30 seconds is considered uncontrolled.
WINDOW_SECONDS = 30.0 #throwing away old readings

class FireAssessor:
    def __init__(self):
        self.temps = deque() #holds upcoming temperature readings as (timestamp, celsius) pairs.
        self.fire_since = None #timestamp for when the fire appeared, it there is no it's None
        self.prev_area = 0.0 #check if the fire is growing

    #calling this every time Thermo sensor sends a reading
    def add_temp(self, temp, now=None):
        if now is None:
            now = time.time()    
        self.temps.append((now, temp)) #saving a reading as a tuple of (timestamp, temperature)
        # Drop readings older than the window
        while self.temps and now - self.temps[0][0] > WINDOW_SECONDS: #looking at the oldest readinfg in the file
            self.temps.popleft() #throwing away old reading

    #Checking changes in the temperature in degrees per minute
    def temp_rise_per_min(self):
        if len(self.temps) < 2:
            return 0.0 #to calculate changes at least 2 data points are needed
        t_old, v_old = self.temps[0]   # oldest timestamp and temperature in the window
        t_new, v_new = self.temps[-1]  # newest reading
        seconds = t_new - t_old #time between oldest and newest readings
        if seconds < 1:
            return 0.0 # prevent division by zero or unusual readings if data comes too fast
        return (v_new - v_old) / seconds * 60.0 #calculate degrees per second and converst it to degrees per minute 

    #returns 'no_fire', 'controlled' or 'UNCONTROLLED'.
    def assess(self, fire_conf=0.0, fire_area=0.0, now=None):
        
        if now is None:
            now = time.time()

        #Is there fire at all?
        if fire_conf < CONF_THRESHOLD: # if fire_conf is lower than 50%
            self.fire_since = None # assume there is no fire
            self.prev_area = 0.0 #resetting flame size history
            return "no_fire"

        # Fire exists - is it controlled?
        if self.fire_since is None: #checking if it's first time seeing the fire
            self.fire_since = now # start the time
        duration = now - self.fire_since #counting for how long the fire is seen

        # compare if its growing comparing to existing previous size
        growing = self.prev_area > 0 and fire_area > self.prev_area * GROWTH_FACTOR #checking if the fire is 20% higher compared to the previous time
        self.prev_area = fire_area

        rising_fast = self.temp_rise_per_min() > RISE_LIMIT #calls the function if it grows faster than 10 degrees
        too_long = duration > DURATION_LIMIT #chescks if its for longer than 30 seconds

        if growing or rising_fast or too_long: #if conditions are triggered is classified as uncontrolled
            return "UNCONTROLLED"
        return "controlled"

#testing
if __name__ == "__main__":
    a = FireAssessor()
    t = 1000.0                          
    print("no fire: ", a.assess(0.1, 0.0, now=t))
    t += 1
    print("small flame: ", a.assess(0.9, 0.05, now=t))
    t += 1
    print("same size: ", a.assess(0.9, 0.05, now=t))
    t += 1
    print("flame bigger: ", a.assess(0.9, 0.10, now=t)) # UNCONTROLLED

