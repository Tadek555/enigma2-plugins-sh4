# -*- coding: utf-8 -*-
# for localized messages
from __init__ import _
from enigma import eTimer, getDesktop
from Screens.Screen import Screen
from Screens.MessageBox import MessageBox
from Components.Label import Label
from Components.ActionMap import ActionMap, NumberActionMap
from Components.Sources.List import List
from Components.Network import iNetwork
from Components.Input import Input
from Tools.Directories import resolveFilename, SCOPE_PLUGINS, SCOPE_SKIN_IMAGE
from Tools.LoadPixmap import LoadPixmap
from cPickle import dump, load
from os import path as os_path, stat, mkdir, remove
from time import time
from stat import ST_MTIME

import netscan
from MountManager import AutoMountManager
from AutoMount import iAutoMount
from MountEdit import AutoMountEdit
from UserDialog import UserDialog

def write_cache(cache_file, cache_data):
	#Does a cPickle dump
	if not os_path.isdir( os_path.dirname(cache_file) ):
		try:
			mkdir( os_path.dirname(cache_file) )
		except OSError:
			print os_path.dirname(cache_file), 'is a file'
	fd = open(cache_file, 'w')
	dump(cache_data, fd, -1)
	fd.close()

def valid_cache(cache_file, cache_ttl):
	#See if the cache file exists and is still living
	try:
		mtime = stat(cache_file)[ST_MTIME]
	except:
		return 0
	curr_time = time()
	if (curr_time - mtime) > cache_ttl:
		return 0
	else:
		return 1

def load_cache(cache_file):
	#Does a cPickle load
	fd = open(cache_file)
	cache_data = load(fd)
	fd.close()
	return cache_data

class NetworkDescriptor:
	def __init__(self, name = "NetworkServer", description = ""):
		self.name = name
		self.description = description

class NetworkBrowser(Screen):
	skin = """
		<screen name="NetworkBrowser" position="90,80" size="560,450" title="Network Neighbourhood">
			<ePixmap pixmap="skin_default/bottombar.png" position="10,360" size="540,120" zPosition="1" transparent="1" alphatest="on" />
			<widget source="list" render="Listbox" position="10,10" size="540,350" zPosition="10" scrollbarMode="showOnDemand">
				<convert type="TemplatedMultiContent">
					{"template": [
							MultiContentEntryPixmapAlphaTest(pos = (0, 0), size = (48, 48), png = 1), # index 1 is the expandable/expanded/verticalline icon
							MultiContentEntryText(pos = (50, 4), size = (420, 26), font=2, flags = RT_HALIGN_LEFT, text = 2), # index 2 is the Hostname
							MultiContentEntryText(pos = (140, 5), size = (320, 25), font=0, flags = RT_HALIGN_LEFT, text = 3), # index 3 is the sharename
							MultiContentEntryText(pos = (140, 26), size = (320, 17), font=1, flags = RT_HALIGN_LEFT, text = 4), # index 4 is the sharedescription
							MultiContentEntryPixmapAlphaTest(pos = (45, 0), size = (48, 48), png = 5), # index 5 is the nfs/cifs icon
							MultiContentEntryPixmapAlphaTest(pos = (90, 0), size = (48, 48), png = 6), # index 6 is the isMounted icon
						],
					"fonts": [gFont("Regular", 20),gFont("Regular", 14),gFont("Regular", 24)],
					"itemHeight": 50
					}
				</convert>
			</widget>
			<ePixmap pixmap="skin_default/buttons/button_green.png" position="30,370" zPosition="10" size="15,16" transparent="1" alphatest="on" />
			<widget name="mounttext" position="50,370" size="250,21" zPosition="10" font="Regular;21" transparent="1" />
			<ePixmap pixmap="skin_default/buttons/button_blue.png" position="30,395" zPosition="10" size="15,16" transparent="1" alphatest="on" />
			<widget name="searchtext" position="50,395" size="150,21" zPosition="10" font="Regular;21" transparent="1" />
			<widget name="infotext" position="300,375" size="250,21" zPosition="10" font="Regular;21" transparent="1" />
			<ePixmap pixmap="skin_default/buttons/button_red.png" position="410,420" zPosition="10" size="15,16" transparent="1" alphatest="on" />
			<widget name="closetext" position="430,420" size="120,21" zPosition="10" font="Regular;21" transparent="1" />
			<ePixmap pixmap="skin_default/buttons/button_yellow.png" position="30,420" zPosition="10" size="15,16" transparent="1" alphatest="on" />
			<widget name="rescantext" position="50,420" size="300,21" zPosition="10" font="Regular;21" transparent="1" />
		</screen>"""

	def __init__(self, session, iface,plugin_path):
		Screen.__init__(self, session)
		self.skin_path = plugin_path
		self.session = session
		self.iface = iface
		if self.iface is None:
			self.iface = 'eth0'
		self.networklist = None
		self.device = None
		self.mounts = None
		self.expanded = []
		self.cache_ttl = 604800 #Seconds cache is considered valid, 7 Days should be ok
		self.cache_file = '/etc/enigma2/networkbrowser.cache' #Path to cache directory

		self["closetext"] = Label(_("Close"))
		self["mounttext"] = Label(_("Mounts management"))
		self["rescantext"] = Label(_("Rescan network"))
		self["infotext"] = Label(_("Press OK to mount!"))
		self["searchtext"] = Label(_("Scan IP"))

		self["shortcuts"] = ActionMap(["ShortcutActions", "WizardActions"],
		{
			"ok": self.go,
			"back": self.close,
			"red": self.close,
			"green": self.keyGreen,
			"yellow": self.keyYellow,
			"blue": self.keyBlue,
		})

		self.list = []
		self.statuslist = []
		self.listindex = 0
		self["list"] = List(self.list)
		self["list"].onSelectionChanged.append(self.selectionChanged)

		self.onLayoutFinish.append(self.startRun)
		self.onShown.append(self.setWindowTitle)
		self.onClose.append(self.cleanup)
		self.Timer = eTimer()
		self.Timer.callback.append(self.TimerFire)

	def cleanup(self):
		del self.Timer
		iAutoMount.stopMountConsole()
		iNetwork.stopRestartConsole()
		iNetwork.stopGetInterfacesConsole()

	def startRun(self):
		self.setStatus('update')
		self.mounts = iAutoMount.getMountsList()
		self["infotext"].hide()
		self.vc = valid_cache(self.cache_file, self.cache_ttl)
		if self.cache_ttl > 0 and self.vc != 0:
			self.process_NetworkIPs()
		else:
			self.Timer.start(3000)

	def TimerFire(self):
		self.Timer.stop()
		self.process_NetworkIPs()

	def setWindowTitle(self):
		self.setTitle(_("Browse network neighbourhood"))

	def keyGreen(self):
		self.session.open(AutoMountManager, None, self.skin_path)

	def keyYellow(self):
		if (os_path.exists(self.cache_file) == True):
			remove(self.cache_file)
		self.startRun()

	def keyBlue(self):
		self.session.openWithCallback(self.scanIPclosed,ScanIP)

	def scanIPclosed(self,result):
		if result:
			print "got IP:",result
			nwlist = []
			if len(result):
				strIP = str(result) + "/24"
				nwlist.append(netscan.netzInfo(strIP))
				self.networklist = nwlist[0]
		if len(self.networklist) > 0:
			self.updateHostsList()

	def setStatus(self,status = None):
		if status:
			self.statuslist = []
			if status == 'update':
				statuspng = LoadPixmap(cached=True, path=resolveFilename(SCOPE_PLUGINS, "SystemPlugins/NetworkBrowser/icons/update.png"))
				self.statuslist.append(( ['info'], statuspng, _("Searching your network. Please wait..."), None, None, None, None ))
				self['list'].setList(self.statuslist)
			elif status == 'error':
				statuspng = LoadPixmap(cached=True, path=resolveFilename(SCOPE_PLUGINS, "SystemPlugins/NetworkBrowser/icons/error.png"))
				self.statuslist.append(( ['info'], statuspng, _("No network devices found!"), None, None, None, None ))
				self['list'].setList(self.statuslist)

	def process_NetworkIPs(self):
		self.inv_cache = 0
		self.vc = valid_cache(self.cache_file, self.cache_ttl)
		if self.cache_ttl > 0 and self.vc != 0:
			print 'Loading network cache from ',self.cache_file
			try:
				self.networklist = load_cache(self.cache_file)
			except:
				self.inv_cache = 1
		if self.cache_ttl == 0 or self.inv_cache == 1 or self.vc == 0:
			print 'Getting fresh network list'
			self.networklist = self.getNetworkIPs()
			write_cache(self.cache_file, self.networklist)
		if len(self.networklist) > 0:
			self.updateHostsList()
		else:
			self.setStatus('error')

	def getNetworkIPs(self):
		nwlist = []
		sharelist = []
		self.IP = iNetwork.getAdapterAttribute(self.iface, "ip")
		if len(self.IP):
			strIP = str(self.IP[0]) + "." + str(self.IP[1]) + "." + str(self.IP[2]) + ".0/24"
			nwlist.append(netscan.netzInfo(strIP))
		tmplist = nwlist[0]
		return tmplist

	def getNetworkShares(self,hostip,hostname,devicetype):
		sharelist = []
		self.sharecache_file = None
		self.sharecache_file = '/etc/enigma2/' + hostname.strip() + '.cache' #Path to cache directory
		if os_path.exists(self.sharecache_file):
			print 'Loading userinfo from ',self.sharecache_file
			try:
				self.hostdata = load_cache(self.sharecache_file)
				username = self.hostdata['username']
				password = self.hostdata['password']
			except:
				username = "username"
				password = "password"
		else:
			username = "username"
			password = "password"

		if devicetype == 'unix':
			smblist=netscan.smbShare(hostip,hostname,username,password)
			for x in smblist:
				if len(x) == 6:
					if x[3] != 'IPC$':
						sharelist.append(x)
			nfslist=netscan.nfsShare(hostip,hostname)
			for x in nfslist:
				if len(x) == 6:
					sharelist.append(x)
		else:
			smblist=netscan.smbShare(hostip,hostname,username,password)
			for x in smblist:
				if len(x) == 6:
					if x[3] != 'IPC$':
						sharelist.append(x)
		return sharelist

	def updateHostsList(self):
		self.list = []
		self.network = {}
		for x in self.networklist:
			if not self.network.has_key(x[2]):
				self.network[x[2]] = []
			self.network[x[2]].append((NetworkDescriptor(name = x[1], description = x[2]), x))
		self.network.keys().sort()
		for x in self.network.keys():
			hostentry = self.network[x][0][1]
			name = hostentry[2] + " ( " +hostentry[1].strip() + " )"
			print hostentry
			expandableIcon = LoadPixmap(cached=True, path=resolveFilename(SCOPE_PLUGINS, "SystemPlugins/NetworkBrowser/icons/host.png"))
			self.list.append(( hostentry, expandableIcon, name, None, None, None, None ))
		self["list"].setList(self.list)
		self["list"].setIndex(self.listindex)

	def updateNetworkList(self):
		self.list = []
		self.network = {}
		for x in self.networklist:
			if not self.network.has_key(x[2]):
				self.network[x[2]] = []
			self.network[x[2]].append((NetworkDescriptor(name = x[1], description = x[2]), x))
		self.network.keys().sort()
		for x in self.network.keys():
			if self.network[x][0][1][3] == '00:00:00:00:00:00':
				self.device = 'unix'
			else:
				self.device = 'windows'
			if x in self.expanded:
				networkshares = self.getNetworkShares(x,self.network[x][0][1][1].strip(),self.device)
				hostentry = self.network[x][0][1]
				name = hostentry[2] + " ( " +hostentry[1].strip() + " )"
				expandedIcon = LoadPixmap(cached=True, path=resolveFilename(SCOPE_PLUGINS, "SystemPlugins/NetworkBrowser/icons/host.png"))
				self.list.append(( hostentry, expandedIcon, name, None, None, None, None ))
				for share in networkshares:
					self.list.append(self.BuildNetworkShareEntry(share))
			else: # HOSTLIST - VIEW
				hostentry = self.network[x][0][1]
				name = hostentry[2] + " ( " +hostentry[1].strip() + " )"
				expandableIcon = LoadPixmap(cached=True, path=resolveFilename(SCOPE_PLUGINS, "SystemPlugins/NetworkBrowser/icons/host.png"))
				self.list.append(( hostentry, expandableIcon, name, None, None, None, None ))
		self["list"].setList(self.list)
		self["list"].setIndex(self.listindex)

	def BuildNetworkShareEntry(self,share):
		verticallineIcon = LoadPixmap(cached=True, path=resolveFilename(SCOPE_PLUGINS, "SystemPlugins/NetworkBrowser/icons/verticalLine.png"))
		sharetype = share[0]
		localsharename = share[1]
		sharehost = share[2]

		if sharetype == 'smbShare':
			sharedir = share[3]
			sharedescription = share[5]
		else:
			sharedir = share[4]
			sharedescription = share[3]

		if sharetype == 'nfsShare':
			newpng = LoadPixmap(cached=True, path=resolveFilename(SCOPE_PLUGINS, "SystemPlugins/NetworkBrowser/icons/i-nfs.png"))
		else:
			newpng = LoadPixmap(cached=True, path=resolveFilename(SCOPE_PLUGINS, "SystemPlugins/NetworkBrowser/icons/i-smb.png"))

		self.isMounted = False
		for sharename, sharedata in self.mounts.items():
			if sharedata['ip'] == sharehost:
				if sharetype == 'nfsShare' and sharedata['mounttype'] == 'nfs':
					if sharedir == sharedata['sharedir']:
						if sharedata["isMounted"] is True:
							self.isMounted = True
				if sharetype == 'smbShare' and sharedata['mounttype'] == 'cifs':
					if sharedir == sharedata['sharedir']:
						if sharedata["isMounted"] is True:
							self.isMounted = True
		if self.isMounted is True:
			isMountedpng = LoadPixmap(cached=True, path=resolveFilename(SCOPE_PLUGINS, "SystemPlugins/NetworkBrowser/icons/ok.png"))
		else:
			isMountedpng = LoadPixmap(cached=True, path=resolveFilename(SCOPE_PLUGINS, "SystemPlugins/NetworkBrowser/icons/cancel.png"))

		return((share, verticallineIcon, None, sharedir, sharedescription, newpng, isMountedpng))

	def selectionChanged(self):
		current = self["list"].getCurrent()
		self.listindex = self["list"].getIndex()
		print len(current)
		if current:
			if current[0][0] in ("nfsShare", "smbShare"):
				self["infotext"].show()
			else:
				self["infotext"].hide()

	def go(self):
		sel = self["list"].getCurrent()
		if sel is None:
			return
		if len(sel[0]) <= 1:
			return
		selectedhost = sel[0][2]
		selectedhostname = sel[0][1]

		self.hostcache_file = None
		if sel[0][0] == 'host': # host entry selected
			if selectedhost in self.expanded:
				self.expanded.remove(selectedhost)
				self.updateNetworkList()
			else:
				self.hostcache_file = '/etc/enigma2/' + selectedhostname.strip() + '.cache' #Path to cache directory
				if os_path.exists(self.hostcache_file):
					print 'Loading userinfo cache from ',self.hostcache_file
					try:
						self.hostdata = load_cache(self.hostcache_file)
						self.passwordQuestion(False)
					except:
						self.session.openWithCallback(self.passwordQuestion, MessageBox, (_("Do you want to enter a username and password for this host?\n") ) )
				else:
					self.session.openWithCallback(self.passwordQuestion, MessageBox, (_("Do you want to enter a username and password for this host?\n") ) )
		if sel[0][0] == 'nfsShare': # share entry selected
			self.openMountEdit(sel[0])
		if sel[0][0] == 'smbShare': # share entry selected
			self.openMountEdit(sel[0])

	def passwordQuestion(self, ret = False):
		sel = self["list"].getCurrent()
		selectedhost = sel[0][2]
		selectedhostname = sel[0][1]
		if (ret == True):
			self.session.openWithCallback(self.UserDialogClosed, UserDialog, self.skin_path, selectedhostname.strip())
		else:
			if sel[0][0] == 'host': # host entry selected
				if selectedhost in self.expanded:
					self.expanded.remove(selectedhost)
				else:
					self.expanded.append(selectedhost)
				self.updateNetworkList()
			if sel[0][0] == 'nfsShare': # share entry selected
				self.openMountEdit(sel[0])
			if sel[0][0] == 'smbShare': # share entry selected
				self.openMountEdit(sel[0])

	def UserDialogClosed(self, *ret):
		if ret is not None and len(ret):
			self.go()

	def openMountEdit(self, selection):
		if selection is not None and len(selection):
			mounts = iAutoMount.getMountsList()
			if selection[0] == 'nfsShare': # share entry selected
				#Initialize blank mount enty
				data = { 'isMounted': False, 'active': False, 'ip': False, 'sharename': False, 'sharedir': False, 'username': False, 'password': False, 'mounttype' : False, 'options' : False }
				# add data
				data['mounttype'] = 'nfs'
				data['active'] = True
				data['ip'] = selection[2]
				data['sharename'] = selection[1]
				data['sharedir'] = selection[4]
				data['options'] = "rw,nolock"

				for sharename, sharedata in mounts.items():
					if sharedata['ip'] == selection[2] and sharedata['sharedir'] == selection[4]:
						data = sharedata
				self.session.openWithCallback(self.MountEditClosed,AutoMountEdit, self.skin_path, data)
			if selection[0] == 'smbShare': # share entry selected
				#Initialize blank mount enty
				data = { 'isMounted': False, 'active': False, 'ip': False, 'sharename': False, 'sharedir': False, 'username': False, 'password': False, 'mounttype' : False, 'options' : False }
				# add data
				data['mounttype'] = 'cifs'
				data['active'] = True
				data['ip'] = selection[2]
				data['sharename'] = selection[1]
				data['sharedir'] = selection[3]
				data['options'] = "rw"
				self.sharecache_file = None
				self.sharecache_file = '/etc/enigma2/' + selection[1].strip() + '.cache' #Path to cache directory
				if os_path.exists(self.sharecache_file):
					print 'Loading userinfo from ',self.sharecache_file
					try:
						self.hostdata = load_cache(self.sharecache_file)
						print "self.hostdata", self.hostdata
						data['username'] = self.hostdata['username']
						data['password'] = self.hostdata['password']
					except:
						data['username'] = "username"
						data['password'] = "password"
				else:
					data['username'] = "username"
					data['password'] = "password"

				for sharename, sharedata in mounts.items():
					if sharedata['ip'] == selection[2].strip() and sharedata['sharedir'] == selection[3].strip():
						data = sharedata
				self.session.openWithCallback(self.MountEditClosed,AutoMountEdit, self.skin_path, data)

	def MountEditClosed(self, returnValue = None):
		if returnValue == None:
			self.updateNetworkList()

class ScanIP(Screen):
	skin = """
		<screen name="IPKGSource" position="100,100" size="550,80" title="IPKG source" >
			<widget name="text" position="10,10" size="530,25" font="Regular;20" backgroundColor="background" foregroundColor="#cccccc" />
			<ePixmap pixmap="skin_default/buttons/red.png" position="10,40" zPosition="2" size="140,40" transparent="1" alphatest="on" />
			<widget name="closetext" position="20,50" size="140,21" zPosition="10" font="Regular;21" transparent="1" />
			<ePixmap pixmap="skin_default/buttons/green.png" position="160,40" zPosition="2" size="140,40" transparent="1" alphatest="on" />
			<widget name="edittext" position="170,50" size="300,21" zPosition="10" font="Regular;21" transparent="1" />
		</screen>"""

	def __init__(self, session):
		Screen.__init__(self, session)
		self.session = session
		text = ""

		desk = getDesktop(0)
		x= int(desk.size().width())
		y= int(desk.size().height())
		#print "[IPKGSource] mainscreen: current desktop size: %dx%d" % (x,y)

		self["closetext"] = Label(_("Cancel"))
		self["edittext"] = Label(_("OK"))

		if (y>=720):
			self["text"] = Input(text, maxSize=False, type=Input.TEXT)
		else:
			self["text"] = Input(text, maxSize=False, visible_width = 55, type=Input.TEXT)

		self["actions"] = NumberActionMap(["WizardActions", "InputActions", "TextEntryActions", "KeyboardInputActions","ShortcutActions"],
		{
			"ok": self.go,
			"back": self.exit,
			"red": self.exit,
			"green": self.go,
			"left": self.keyLeft,
			"right": self.keyRight,
			"home": self.keyHome,
			"end": self.keyEnd,
			"deleteForward": self.keyDeleteForward,
			"deleteBackward": self.keyDeleteBackward,
			"1": self.keyNumberGlobal,
			"2": self.keyNumberGlobal,
			"3": self.keyNumberGlobal,
			"4": self.keyNumberGlobal,
			"5": self.keyNumberGlobal,
			"6": self.keyNumberGlobal,
			"7": self.keyNumberGlobal,
			"8": self.keyNumberGlobal,
			"9": self.keyNumberGlobal,
			"0": self.keyNumberGlobal
		}, -1)

		self.onLayoutFinish.append(self.layoutFinished)

	def exit(self):
		self.close(None)

	def layoutFinished(self):
		self.setWindowTitle()
		self["text"].right()

	def setWindowTitle(self):
		self.setTitle(_("Enter IP to scan..."))

	def go(self):
		text = self["text"].getText()
		if text:
			self.close(text)

	def keyLeft(self):
		self["text"].left()

	def keyRight(self):
		self["text"].right()

	def keyHome(self):
		self["text"].home()

	def keyEnd(self):
		self["text"].end()

	def keyDeleteForward(self):
		self["text"].delete()

	def keyDeleteBackward(self):
		self["text"].deleteBackward()

	def keyNumberGlobal(self, number):
		print "pressed", number
		self["text"].number(number)
