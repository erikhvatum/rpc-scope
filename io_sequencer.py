from rpc_acquisition import smart_serial
import time

LUMENCOR_PINS = {
    'UV': 'D6',
    'Blue': 'D5',
    'Cyan': 'D3',
    'Teal': 'D4',
    'GreenYellow': 'D2',
    'Red': 'D1'
}

CAMERA_PINS = {
    'Trigger': 'B0',
    'Arm': 'B1',
    'Fire': 'B2',
    'AuxOut1': 'B3'
}

TL_ENABLE_PIN = 'E6'
TL_PWM_PIN = 'D7'
TL_PWM_MAX = 255

class Command:
    @classmethod
    def _make_command(cls, *elements):
        return ' '.join(map(str, elements))
    
    @classmethod
    def wait_high(cls, pin):
        return cls._make_command('wh', pin)

    @classmethod
    def wait_low(cls, pin):
        return cls._make_command('wl', pin)
        
    @classmethod
    def wait_change(cls, pin):
        return cls._make_command('wc', pin)

    @classmethod
    def wait_time(cls, time):
        return cls._make_command('wt', time)

    @classmethod
    def raw_wait_high(cls, pin):
        return cls._make_command('rh', pin)

    @classmethod
    def raw_wait_low(cls, pin):
        return cls._make_command('rl', pin)
        
    @classmethod
    def raw_wait_change(cls, pin):
        return cls._make_command('rc', pin)

    @classmethod
    def delay_ms(cls, delay):
        return cls._make_command('dm', delay)

    @classmethod
    def delay_us(cls, delay):
        return cls._make_command('du', delay)
    
    @classmethod
    def pwm(cls, pin, value):
        return cls._make_command('pm', pin, value)

    @classmethod
    def set_high(cls, pin):
        return cls._make_command('sh', pin)

    @classmethod
    def set_low(cls, pin):
        return cls._make_command('sl', pin)
        
    @classmethod
    def set_tristate(cls, pin):
        return cls._make_command('st', pin)
    
    @classmethod
    def char_transmit(cls, byte):
        return cls._make_command('ct', byte)
    
    @classmethod
    def char_receive(cls):
        return cls._make_command('cr')

    @classmethod
    def loop(cls, index, count):
        return cls._make_command('lo', index, count)
    
    @classmethod
    def goto(cls, index):
        return cls._make_command('go', index)

    @classmethod
    def lumencor_lamps(cls, **lamps):
        """Input keyword arguments must be lamp names specified in LUMENCOR_PINS
        keys. The values are either True to enable that lamp, False to disable,
        or None to do nothing (unspecified lamps are also not altered)."""
        command = []
        for lamp, enable in lamps.items():
            if enable is None:
                continue
            pin = LUMENCOR_PINS[lamp]
            if enable:
                command.append(cls.set_high(pin))
            else:
                command.append(cls.set_low(pin))
        return '\n'.join(command)

    @classmethod
    def transmitted_lamp(cls, enable=None, intensity=None):
        """enable: True (lamp on), False (lamp off), or None (no change).
        intensity: None (no change) or value in the range [0, 1] for min to max.
        """
        command = []
        if pwm is not None:
            pwm_value = int(round(value*TL_PWM_MAX))
            command.append(cls.pwm(TL_PWM_PIN, pwm_value))
        if enable is not None:
            if enable:
                command.append(cls.set_high(TL_ENABLE_PIN))
            else:
                command.append(cls.set_low(TL_ENABLE_PIN))
        return '\n'.join(command)


class PedalWaiter:    
    def __init__(self, pin, iotool, pressed_is_high=True, bounce_time=0.1):
        self.last_time = 0
        self.last_wait = None
        self.iotool = iotool
        self.bounce_time = bounce_time
        self.delay = Command.delay_ms(int(self.bounce_time * 1000))
        if pressed_is_high:
            self.depress = Command.wait_high(pin)
            self.release = Command.wait_low(pin)
        else:
            self.depress = Command.wait_low(pin)
            self.release = Command.wait_high(pin)
    
    def _wait(self, command):
        sleep_time = bounce_time - (time.time() - self.last_time)
        if sleep_time > 0:
            time.sleep(sleep_time)
        self.iotool.start_program(command)
        self.iotool.wait_for_program_done()            
        self.last_time = time.time()
        
    def wait_depress(self):
        self._wait(self.depress)
    
    def wait_release(self):
        self._wait(self.release)
    
    def wait_click(self):
        self.iotool.start_program(self.depress, self.delay, self.release)
        self.iotool.wait_for_program_done()
        self.last_time = time.time()
        

class IOTool:
    def __init__(self, serial_port, serial_baud):
        self._serialport = smart_serial.Serial(serial_port, baudrate=serial_baud)
        self._serialport.write(b'\x80\xFF\n') # disable echo
        self._serialport.read(2) # read back echo of above (no other echoes will come)

    def _send(self, commands):
        command_bytes = bytes('\n'.join(commands) + '\n', encoding='ascii')
        self._serialport.write(command_bytes)
    
    def execute(self, *commands):
        self._send(commands)

    def assert_empty_buffer(self):
        buffered = self._serialport.read_all_buffered()
        if buffered:
            raise RuntimeError('Unexpected IOTool output: {}'.format(str(buffered, encoding='ascii')))
    
    def store_program(self, *commands):
        self.assert_empty_buffer()
        self._send(['program'] + list(commands) + ['end'])
        response = self._serialport.read_until(b'OK\r\n')[:-4] # see if there was any output before the 'OK'
        if response:
            raise RuntimeError('Program error: {}'.format(str(response, encoding='ascii')))
    
    def start_program(self, *commands, iters=1):
        if commands:
            self.store_program(*commands)
        self._serialport.write(b'run {}\n'.format(iters))
    
    def wait_for_serial_char(self):
        self._serialport.read(1)
    
    def _wait_for_program_done(self):
        self._serialport.read_until(b'DONE\r\n')
    
    def wait_for_program_done(self):
        try:
            self._wait_for_program_done()
        except KeyboardInterrupt as k:
            self.stop_program()
            raise k
        
    def stop_program(self):
        self.stop()
        self._wait_for_program_done()
        
    def stop(self):
        self._serialport.write(b'!')
    
