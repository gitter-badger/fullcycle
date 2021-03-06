'''# Miner Helper functions
# Skylake Software, Inc
#"bitmain-fan-ctrl" : true,
#"bitmain-fan-pwm" : "80",
'''
import time
import datetime
from helpers.minerapi import MinerApi
from helpers.ssh import Ssh
from domain.mining import Miner, MinerInfo, MinerStatistics, MinerCurrentPool, MinerAccessLevel, MinerApiCall

class MinerMonitorException(Exception):
    """Happens during monitoring of miner"""
    def friendlymessage(self):
        msg = getattr(self, 'message', repr(self))
        return msg

    def istimedout(self):
        return self.friendlymessage().find('timed out') >= 0
    def isconnectionrefused(self):
        return self.friendlymessage().find('ConnectionRefusedError') >= 0

class MinerCommandException(Exception):
    """Happens during executing miner command"""

def stats(miner: Miner):
    '''returns MinerStatistics, MinerInfo, and MinerApiCall'''
    if not miner.can_monitor():
        raise MinerMonitorException('miner {0} cannot be monitored. ip={1} port={2}'.format(miner.name, miner.ipaddress, miner.port))

    try:
        thecall = MinerApiCall(miner)
        entity = MinerStatistics(miner, when=datetime.datetime.utcnow())
        api = MinerApi(host=miner.ipaddress, port=int(miner.port))
        
        thecall.start()
        #jstats = api.stats()
        stats_and_pools = api.command('stats+pools')
        thecall.stop()
        if 'stats' in stats_and_pools:
            jstats = stats_and_pools['stats'][0]
        else:
            #if call failed then only one result is returned, so parse it
            jstats = stats_and_pools
        entity.rawstats = jstats
        jstatus = jstats['STATUS']
        if jstatus[0]['STATUS'] == 'error':
            if not miner.is_disabled():
                raise MinerMonitorException(jstatus[0]['description'])
        else:
            status = jstats['STATS'][0]
            jsonstats = jstats['STATS'][1]
            #details = jstats['STATS'][1]

            minerinfo = parse_minerinfo(status)

            #build MinerStatistics from stats
            parse_statistics(entity, jsonstats, status)
            minerpool = parse_minerpool(miner, stats_and_pools['pools'][0])

            return entity, minerinfo, thecall, minerpool
    except BaseException as ex:
        print('Failed to call miner stats api: ' + str(ex))
        raise MinerMonitorException(ex)
    return None, None, None, None

def parse_statistics(entity, jsonstats, status):
    entity.minercount = int(jsonstats['miner_count'])
    entity.elapsed = int(jsonstats['Elapsed'])
    entity.currenthash = int(float(jsonstats['GHS 5s']))
    entity.frequency = jsonstats['frequency']
    minertype = status['Type']
            
    frequencies = {k:v for (k,v) in jsonstats.items() if k.startswith('freq_avg') and v != 0}
    entity.frequency = str(int(sum(frequencies.values()) / len(frequencies)))

    controllertemps = {k:v for (k,v) in jsonstats.items() if k in ['temp6','temp7','temp8']}
    entity.controllertemp = max(controllertemps.values())
    #should be 3
    #tempcount = jsonstats['temp_num']
    boardtemps = {k:v for (k,v) in jsonstats.items() if k.startswith('temp2_') and v != 0}
    boardtempkeys=list(boardtemps.keys())
    if len(boardtemps) > 0:
        entity.tempboard1 = boardtemps[boardtempkeys[0]]
    if len(boardtemps) > 1:
        entity.tempboard2 = boardtemps[boardtempkeys[1]]
    if len(boardtemps) > 2:
        entity.tempboard3 = boardtemps[boardtempkeys[2]]

    fans = {k:v for (k,v) in jsonstats.items() if k.startswith('fan') and k != 'fan_num' and v != 0}
    fankeys=list(fans.keys())
    if len(fans) > 0:
        entity.fan1 = fans[fankeys[0]]
    if len(fans) > 1:
        entity.fan2 = fans[fankeys[1]]
    if len(fans) > 2:
        entity.fan3 = fans[fankeys[2]]

    chains = {k:v for (k,v) in jsonstats.items() if k.startswith('chain_acs') and v != ''}
    chainkeys=list(chains.keys())
    if len(chains) > 0:
        entity.boardstatus1 = chains[chainkeys[0]]
    if len(chains) > 1:
        entity.boardstatus2 = chains[chainkeys[1]]
    if len(chains) > 2:
        entity.boardstatus3 = chains[chainkeys[2]]

def parse_minerinfo(status):
    #build MinerInfo from stats
    minerid = 'unknown'
    minertype = 'unknown'
    if 'Type' in status:
        minertype = status['Type']
    else:
        if toplevelstatus['Description'].startswith('cgminer'):
            minertype = toplevelstatus['Description']
    if 'miner_id' in status:
        minerid = status['miner_id']
    minerinfo = MinerInfo(minertype, minerid)
    return minerinfo

def pools(miner: Miner):
    '''Gets the current pool for the miner'''
    try:
        api = MinerApi(host=miner.ipaddress, port=int(miner.port))
        jstatuspools = api.pools()
        if jstatuspools['STATUS'][0]['STATUS'] == 'error':
            if not miner.is_disabled():
                raise MinerMonitorException(jstatuspools['STATUS'][0]['description'])
        else:
            return parse_minerpool(jstatuspools)
    except BaseException as ex:
        print('Failed to call miner pools api: ' + str(ex))
    return None

def parse_minerpool(miner, jstatuspools):
    def sort_by_priority(j):
        return j['Priority']

    jpools = jstatuspools["POOLS"]
    #sort by priority
    jpools.sort(key=sort_by_priority)
    #try to do elegant way, but not working
    #cPool = namedtuple('Pool', 'POOL, URL, Status,Priority,Quota,Getworks,Accepted,Rejected,Long Poll')
    #colpools = [cPool(**k) for k in jsonpools["POOLS"]]
    #for pool in colpools:
    #    print(pool.POOL)
    for pool in jpools:
        if str(pool["Status"]) == "Alive":
            currentpool = pool["URL"]
            currentworker = pool["User"]
            #print("{0} {1} {2} {3} {4} {5}".format(pool["POOL"],pool["Priority"],pool["URL"],pool["User"],pool["Status"],pool["Stratum Active"]))
            break
    minerpool = MinerCurrentPool(miner, currentpool, currentworker, jstatuspools)
    return minerpool

def getminerlcd(miner: Miner):
    '''gets a summary (quick display values) for the miner'''
    try:
        api = MinerApi(host=miner.ipaddress, port=int(miner.port))
        jstatuspools = api.lcd()
        return jstatuspools
    except BaseException as ex:
        return str(ex)

def setminertoprivileged(miner, login, allowsetting):
    try:
        mineraccess = privileged(miner)
    except MinerMonitorException as ex:
        if ex.istimedout():
            mineraccess = MinerAccessLevel.Waiting
    if mineraccess == MinerAccessLevel.Restricted or mineraccess == MinerAccessLevel.Waiting:
        if mineraccess == MinerAccessLevel.Restricted:
            setprivileged(miner, login, allowsetting)
        #todo: not ideal to wait in a loop here, need a pattern that will wait in non blocking mode
        waitforonline(miner)
        mineraccess = privileged(miner)
    return mineraccess

def privileged(miner: Miner):
    '''gets status: privileged or restricted'''
    api = MinerApi(host=miner.ipaddress, port=int(miner.port))
    apiresponse = api.privileged()
    jstatus = apiresponse["STATUS"][0]
    if jstatus is not None and jstatus["STATUS"] == "S":
        return MinerAccessLevel.Privileged
    return MinerAccessLevel.Restricted

#restart (*)   none           Status is a single "RESTART" reply before cgminer restarts
def restart(miner: Miner):
    '''restart miner through api'''
    api = MinerApi(host=miner.ipaddress, port=int(miner.port))
    apiresponse = api.restart()
    print(apiresponse)
    return apiresponse

def print_connection_data(connection):
    if connection.strdata:
        print(connection.strdata)    # print the last line of received data
        print('==========================')
    if connection.alldata:
        print(connection.alldata)   # This contains the complete data received.
        print('==========================')

def print_response(response):
    for line in response:
        print(line)

def getportfromminer(miner: Miner):
    if isinstance(miner.ftpport, int): return miner.ftpport
    if isinstance(miner.ftpport, str) and miner.ftpport:
        tryport = int(miner.ftpport)
        if tryport > 0: return tryport
    return 22

def getminerconfig(miner: Miner, login):
    '''ger the miner config file'''
    connection = Ssh(miner.ipaddress, login.username, login.password, port=getportfromminer(miner))
    config = connection.exec_command('cat /config/{0}.conf'.format(getminerfilename(miner)))
    connection.close_connection()
    return config

def stopmining(miner: Miner, login):
    miner_shell_command(miner, login, 'restart', 15)

def restartmining(miner: Miner, login):
    miner_shell_command(miner, login, 'restart', 15)

def miner_shell_command(miner: Miner, login, command, timetorun):
    '''send the command stop/restart to miner shell command'''
    connection = Ssh(miner.ipaddress, login.username, login.password, port=getportfromminer(miner))
    connection.open_shell()
    connection.send_shell('/etc/init.d/{0}.sh {1}'.format(getminerfilename(miner), command))
    time.sleep(timetorun)
    print_connection_data(connection)
    connection.close_connection()

def changesshpassword(miner: Miner, oldlogin, newlogin):
    """ change the factory ssh password """
    if newlogin.username != oldlogin.username:
        print("changesshpassword: currently username change is not supported. only change password")
        return
    connection = Ssh(miner.ipaddress, oldlogin.username, oldlogin.password, port=getportfromminer(miner))
    connection.open_shell()
    connection.send_shell('echo "{0}:{1}" | chpasswd'.format(newlogin.username, newlogin.password))
    time.sleep(5)
    print_connection_data(connection)
    connection.close_connection()

def reboot(miner: Miner, login):
    """ reboot the miner through ftp """
    connection = Ssh(miner.ipaddress, login.username, login.password, port=getportfromminer(miner))
    connection.open_shell()
    response = connection.exec_command('/sbin/reboot')
    print_connection_data(connection)
    connection.close_connection()
    return response

def shutdown(miner: Miner, login):
    """ shutdown the miner through ftp
    Warning! this will not turn off the power to the machine!
    It will only shut down the operating system. Machine will still be consuming power if power supply
    does not have on/off switch. You will have to manually restart the machine.
    """
    connection = Ssh(miner.ipaddress, login.username, login.password, port=getportfromminer(miner))
    connection.open_shell()
    connection.send_shell('/sbin/poweroff')
    time.sleep(5)
    print_connection_data(connection)
    connection.close_connection()

def waitforonline(miner: Miner):
    #poll miner until it comes up, returns MinerInfo or None for timeout
    cnt = 60
    sleeptime = 5
    minerinfo = None
    while cnt > 0:
        try:
            minerstats, minerinfo, apicall, minerpool = stats(miner)
            return minerinfo
        except MinerMonitorException as ex:
            if not ex.istimedout() and not ex.isconnectionrefused():
                raise ex
            else:
                print(ex.friendlymessage())

        if minerinfo is not None:
            if minerinfo.miner_type:
                print('   found {0} {1}'.format(minerinfo.miner_type, minerinfo.minerid))
                cnt = 0
        if cnt > 0:
            cnt -= sleeptime
            print('Waiting for {0}...'.format(miner.name))
            time.sleep(sleeptime)
    return None

#The 'poolpriority' command can be used to reset the priority order of multiple
#pools with a single command - 'switchpool' only sets a single pool to first priority
#Each pool should be listed by id number in order of preference (first = most preferred)
#Any pools not listed will be prioritised after the ones that are listed, in the
#priority order they were originally
#If the priority change affects the miner's preference for mining, it may switch immediately
def switch(miner: Miner, poolnumber):
    api = MinerApi(host=miner.ipaddress, port=int(miner.port))
    jswitch = api.switchpool("{0}".format(poolnumber))
    print(jswitch["STATUS"][0]["Msg"])

 #addpool|URL,USR,PASS (*)
 #              none           There is no reply section just the STATUS section
 #                             stating the results of attempting to add pool N
 #                             The Msg includes the pool number and URL
 #                             Use '\\' to get a '\' and '\,' to include a comma
 #                             inside URL, USR or PASS
def addpool(miner: Miner, pool):
    """ Add a pool to a miner. Allows user to select it from drop down and easily switch to it """
    api = MinerApi(host=miner.ipaddress, port=int(miner.port))
    jaddpool = api.addpool("{0},{1},{2}".format(pool.url, pool.user, "x"))
    return jaddpool["STATUS"][0]["Msg"]

def getminerfilename(miner: Miner):
    '''cgminer for D3 and A3'''
    minerfilename = 'cgminer'
    if miner.miner_type.startswith('Antminer S9'):
        minerfilename = 'bmminer'
    return minerfilename

def change_setting(settingkey, newvalue):
    '''todo:there is bug here if updating the last line of config file! command (,) not needed at end'''
    return "sed -i \'s_^\\(\"{0}\" : \\).*_\\1\"{1}\",_\'".format(settingkey, newvalue)

def get_changeconfigcommands(configfilename, setting, newvalue):
    commands = []
    commands.append('cd /config')
    commands.append('cp {0}.conf {1}_last.conf'.format(configfilename, configfilename))
    commands.append('chmod u=rw {0}.conf'.format(configfilename))
    commands.append("{0} {1}.conf".format(change_setting(setting, newvalue), configfilename))
    commands.append('chmod u=r {0}.conf'.format(configfilename))
    return commands

def sendcommands_and_restart(miner: Miner, login, commands):
    stopmining(miner, login)
    try:
        connection = Ssh(miner.ipaddress, login.username, login.password, port=getportfromminer(miner))
        connection.open_shell()
        for cmd in commands:
            connection.send_shell(cmd)
        time.sleep(5)
        print_connection_data(connection)
        connection.close_connection()
    finally:
        restartmining(miner, login)

def setprivileged(miner: Miner, login, allowsetting):
    """ Set miner to privileged mode """
    commands = get_changeconfigcommands(getminerfilename(miner), 'api-allow', allowsetting)
    sendcommands_and_restart(miner, login, commands)

def setrestricted(miner: Miner, login, allowsetting):
    """ Set miner to restricted mode """
    commands = get_changeconfigcommands(getminerfilename(miner), 'api-allow', allowsetting)
    sendcommands_and_restart(miner, login, commands)

def set_frequency(miner: Miner, login, frequency):
    """ Set miner frequency
    Does not work for S9 with auto tune.
    Fixed frequency firmware (650m) has to be loaded first before frequency can be adjusted
    """
    #default for S9 is 550
    #"bitmain-freq" : "550",
    commands = get_changeconfigcommands(getminerfilename(miner), 'bitmain-freq', frequency)
    sendcommands_and_restart(miner, login, commands)

def load_firmware():
    """
    TODO: load firmware file
    this will probably change the ip address of the miner
    """
    pass

def load_miner():
    """
    change the miner software
    """
    #ftp the new miner
    commands = []
    commands.append('cd /usr/bin')
    commands.append('cp bmminer bmminer.original')
    commands.append('cp bmminer880 bmminer')
    commands.append('chmod +x bmminer')
    sendcommands_and_restart(miner, login, commands)

def file_upload(miner, login, localfile, remotefile):
    connection = Ssh(miner.ipaddress, login.username, login.password, port=getportfromminer(miner))
    connection.put(localfile,remotefile)

def file_download(miner, login, localfile, remotefile):
    connection = Ssh(miner.ipaddress, login.username, login.password, port=getportfromminer(miner))
    connection.get(localfile,remotefile)
