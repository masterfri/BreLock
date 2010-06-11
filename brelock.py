#!/usr/bin/env python

import gobject
import random
import os
import sys
import socket
from subprocess import Popen
from subprocess import PIPE
import glob
from xml.dom import minidom
from threading import Thread
import pygtk
pygtk.require("2.0")
import gtk
import gtk.glade
import gettext
import time

class BreLock:

	def __init__(self):

		self.user_homepath = os.getenv('HOME').rstrip('/')
		self.app_data_path = '%s/.brelock/' % (self.user_homepath)
		os.chdir(sys.path[0])

		self.hidden = False
		self.compact = False
		self.passwords = PassStorage()
		self.config = {}
		self.gladefile = "ui.glade"
		self.menus = {}

		self.wTree = gtk.glade.XML(self.gladefile, 'main_window')
		self.window = self.wTree.get_widget("main_window")
		if (self.window):
			self.window.connect("destroy", gtk.main_quit)
		
		gettext.translation('brelock', 'language', languages=['ru']).install(unicode=True)
		self.check_fs()
		self.load_config()
		if not self.load_accounts():
			raise Exception('Terminated by user')
		
		self.wTree.signal_autoconnect({ 
			"on_quit" : self.on_quit,
			"on_about" : self.on_about,
			"on_add_account" : self.on_add_account,
			"on_tree_clicked" : self.on_tree_clicked,
			"on_preferences" : self.on_preferences,
			'on_reload': self.on_reload
		})
		accel = gtk.AccelGroup()
		key, modif = gtk.accelerator_parse('F2')
		accel.connect_group(key, modif, gtk.ACCEL_VISIBLE, lambda a,b,c,d: self.on_edit_account(None))
		key, modif = gtk.accelerator_parse('<Ctrl>C')
		accel.connect_group(key, modif, gtk.ACCEL_VISIBLE, lambda a,b,c,d: self.on_copy_pass(None))
		key, modif = gtk.accelerator_parse('<Alt>C')
		accel.connect_group(key, modif, gtk.ACCEL_VISIBLE, lambda a,b,c,d: self.on_copy_user(None))
		key, modif = gtk.accelerator_parse('<Ctrl><Shift>C')
		accel.connect_group(key, modif, gtk.ACCEL_VISIBLE, lambda a,b,c,d: self.on_copy_account(None))
		key, modif = gtk.accelerator_parse('Delete')
		accel.connect_group(key, modif, gtk.ACCEL_VISIBLE, lambda a,b,c,d: self.on_delete())
		key, modif = gtk.accelerator_parse('<Ctrl>T')
		accel.connect_group(key, modif, gtk.ACCEL_VISIBLE, lambda a,b,c,d: self.on_toggle())
		self.window.add_accel_group(accel)
		
		self.prepare_tree()
		self.display_accounts()
		
		self.statusbar = self.wTree.get_widget("statusbar")
		
		icon = gtk.status_icon_new_from_stock(gtk.STOCK_DIALOG_AUTHENTICATION)
		icon.connect("activate", self.on_activate)
		icon.connect('popup-menu', self.on_icon_menu)
		self.window.connect("delete-event", self.on_close)
		gtk.gdk.threads_init()
		
	def prepare_tree(self):
	
		self.display_tree = self.wTree.get_widget("accouts_display")
		column = gtk.TreeViewColumn('', gtk.CellRendererText(), markup = 0)
		self.display_tree.append_column(column)
		store = DisplayTreeModel()
		self.display_tree.set_model(store)
		
	def load_accounts(self):
	
		try:
			h = open(self.app_data_path + 'accounts.xml', 'r')
			xmlstr = h.read()
			h.close()
			
			if (xmlstr[0:27] == '-----BEGIN PGP MESSAGE-----'):
				print "Data encrypted. Password required"
				while True:
					password = self.require_passw_dialog(_("type your password"))
					if False == password:
						return False
					decxmlstr = self.gpg_decrypt(xmlstr, password)
					if False != decxmlstr:
						print "Data decrypted"
						xmlstr = decxmlstr
						break

			self.passwords.loadXml(xmlstr)
		except Exception, e:
			print "Accounts data missing"

		return True
		
	def save_accounts(self):

		try:
			xmlstr = self.passwords.saveXml();
			
			if self.cfg_get('gpg.isActive'):
				gpgkey = self.cfg_get('gpg.key')
				if None == gpgkey:
					print "Key missing. Encryption impossible!"
					self.cfg_set('gpg.isActive', False)
					self.write_config()
					self.error_message(_("gpg key missing"))
				else:
					encxmlstr = self.gpg_encrypt(xmlstr, gpgkey)
					if False != encxmlstr:
						xmlstr = encxmlstr
						print "Data encrypted"
			else:
				print "Encryption disabled"
			
			f = open(self.app_data_path + 'accounts.xml', 'w')
			f.write(xmlstr)
			f.close()
		except Exception, e:
			print e
			print "Error: Can't flush accounts."
		
	def on_add_account(self, widget, resource=None, login = None):
	
		wTree = gtk.glade.XML(self.gladefile, 'add_account_dialog')
		dialog = wTree.get_widget("add_account_dialog")
		self.bind_pass_gen(wTree)
		self.fill_combo(wTree)
		if resource:
			wTree.get_widget("resource").get_child().set_text(resource)
		if login:
			wTree.get_widget("login").get_child().set_text(login)
		if self.cfg_get('interface.showPass'):
			wTree.get_widget("password").set_visibility(True)
		dialog.show()
		while True:
			response = dialog.run()
			if response == gtk.RESPONSE_OK:
				if self.add_account(dialog, wTree):
					break;
			else:
				break
		dialog.destroy()
		
	def validate_account(self, account, dialog):
	
		if '' == account.resource:
			self.error_message(_("resource missing"), dialog)
			return False
			
		if '' == account.user:
			self.error_message(_("username missing"), dialog)
			return False
			
		if '' == account.password:	
			self.error_message(_("password missing"), dialog)
			return False
			
		return True
		
	def bind_pass_gen(self, wTree):
	
		button = wTree.get_widget("gen_pass")
		entry = wTree.get_widget("password")
		button.connect("clicked", self.on_gen_password, entry)
		
	def on_activate(self, widget):
		
		if self.hidden:
			self.window_restore()
		else:
			self.window_hide()

	def on_close(self, widget, event):

		self.window_hide()
		return True
		
	def window_hide(self):
	
		self.window.hide()
		self.hidden = True
		
	def window_restore(self):
	
		self.window.show()
		self.hidden = False
		
	def on_gen_password(self, button, entry):
	
		password = self.gen_pass()
		entry.set_text(password)
		if self.cfg_get('interface.showPass'):
			return
		wTree = gtk.glade.XML(self.gladefile, 'passgen')
		dialog = wTree.get_widget("passgen")
		wTree.get_widget("pass_container").set_text(password)
		dialog.show()
		dialog.run()
		dialog.destroy()

	def gen_pass(self):
		
		numdig = '0123456789qwertyuiopasdfghjklzxcvbnmQWERTYUIOPASDFGHJKLZXCVBNM'
		symbol = '_-!@#$%^&*()+={}[]:;<>?'
		alphabet = numdig + symbol
		len1 = len(numdig)
		len2 = len(alphabet)
		i = 0
		limit = len2
		password = ''
		while i < 8:
			i = i + 1
			rand = random.randint(0, limit - 1)
			if rand >= len1:
				limit = len1
			password = password + alphabet[rand]
			
		return password
		
	def fill_combo(self, wTree):
	
		resource = wTree.get_widget("resource")
		login = wTree.get_widget("login")
		r = dict()
		l = dict()
		for item in self.passwords.records:
			r[item.resource] = True
			l[item.user] = True
		self.fill_combo_items(resource, r.iterkeys())
		self.fill_combo_items(login, l.iterkeys())
		r.clear()
		l.clear()
		
	def fill_combo_items(self, combo, items):
	
		store = gtk.ListStore(gobject.TYPE_STRING)
		for i in items:
			it = store.append()
			store.set(it, 0, i)
		combo.set_model(store)
		combo.set_text_column(0)
		
	def add_account(self, dialog, wTree):
	
		resource = wTree.get_widget("resource").get_child().get_text()
		login = wTree.get_widget("login").get_child().get_text()
		password = wTree.get_widget("password").get_text()
		tb = wTree.get_widget("notes").get_buffer()
		iter_start, iter_end = tb.get_bounds()
		notes = tb.get_text(iter_start, iter_end)
		account = PassStorageRecord(resource, login, password, notes)
		if not self.validate_account(account, dialog):
			return False	
		if self.passwords.find(account) != -1:
			self.error_message(_("account '%s' exists") % account.nice_name(), dialog)
			return False
		self.passwords.add(account)
		by_user = self.cfg_get('interface.groupByUser')
		self.display_tree.get_model().add_record(account, by_user)
		self.save_accounts()
		self.status(_("account added"))
		return True
		
	def edit_account(self, old_account, dialog, wTree, record):
	
		resource = wTree.get_widget("resource").get_child().get_text()
		login = wTree.get_widget("login").get_child().get_text()
		password = wTree.get_widget("password").get_text()
		tb = wTree.get_widget("notes").get_buffer()
		iter_start, iter_end = tb.get_bounds()
		notes = tb.get_text(iter_start, iter_end)
		new_account = PassStorageRecord(resource, login, password, notes)
		if new_account.is_clone_of(old_account):
			return True
		if not self.validate_account(new_account, dialog):
			return False
		if not new_account == old_account and self.passwords.find(new_account) != -1:
			self.error_message(_("account '%s' exists") % new_account.nice_name(), dialog)
			return False
		old_account.resource = resource
		old_account.user = login
		old_account.password = password
		old_account.notes = notes
		tree, root, leaf = record
		tree.remove(leaf)
		if not tree.iter_children(root):
			tree.remove(root)
		by_user = self.cfg_get('interface.groupByUser')
		tree.add_record(old_account, by_user)
		self.save_accounts()
		self.status(_("account modified"))
		return True
		
	def on_preferences(self, widget):
	
		wTree = gtk.glade.XML(self.gladefile, 'preferences_dialog')
		dialog = wTree.get_widget("preferences_dialog")
		use_left_button = wTree.get_widget("use_left_button")
		show_pass = wTree.get_widget("show_pass")
		group_rc = wTree.get_widget("group_rc")
		group_user = wTree.get_widget("group_user")
		use_gpg = wTree.get_widget("use_gpg")
		gpg_password = wTree.get_widget("gpg_password")
		gpg_password_repeat = wTree.get_widget("gpg_password_repeat")
		gpg_path = wTree.get_widget("gpg_path")

		use_left_button.set_active(self.cfg_get('interface.useLB'))
		show_pass.set_active(self.cfg_get('interface.showPass'))
		if self.cfg_get('interface.groupByUser'):
			group_user.set_active(True)
		else:
			group_rc.set_active(True)
		if self.cfg_get('gpg.isActive'):
			use_gpg.set_active(True)
			wTree.get_widget("label_gpg_pass").set_text(_("change password"))
		gpg_path.set_text(self.cfg_get('gpg.path'))
		use_gpg.connect('toggled', lambda *t: self.toggle_active(use_gpg, (gpg_password, gpg_password_repeat, gpg_path)))
		self.toggle_active(use_gpg, (gpg_password, gpg_password_repeat, gpg_path))
		
		dialog.show()
		while True:
			response = dialog.run()
			if response == gtk.RESPONSE_OK:
				
				# I think it require some comments
				need_update_data = False
				# User require encription
				if use_gpg.get_active():
				
					vgpg_path = gpg_path.get_text()
					# Check the GnuPG tool 
					if not self.check_gnupg(vgpg_path):
						self.error_message(_("can not execute GnuPG '%s'") % vgpg_path, dialog)
						continue

					gpgkey = self.cfg_get('gpg.key')
					# Gpg key not exsists (first time encription?)
					if None == gpgkey:
						password = self.validate_input_pass(dialog, gpg_password, gpg_password_repeat)
						if False == password:
							continue
						print "GnuPG key generation started"
						key = self.gpg_gen_key(password, vgpg_path, dialog)
						print "GnuPG key generation finished"
						if False == key:
							continue
						self.cfg_set('gpg.key', key)
						need_update_data = True
						self.status(_("gpg key generated"))
					# User wants to change password	
					elif gpg_password.get_text() != '':
						password = self.validate_input_pass(dialog, gpg_password, gpg_password_repeat)
						if False == password:
							continue
						oldpassword = self.require_passw_dialog(_("type old password"))
						if False == oldpassword:
							continue
						if not self.gpg_change_passw(gpgkey, password, oldpassword, vgpg_path, dialog):
							continue
						need_update_data = True
						
					# Encription turning off
					elif not self.cfg_get('gpg.isActive'):
						need_update_data = True

					self.cfg_set('gpg.isActive', True)
					self.cfg_set('gpg.path', vgpg_path)
				else:
					# Encription turning on
					if self.cfg_get('gpg.isActive'):
						need_update_data = True
					self.cfg_set('gpg.isActive', False)
				
				# Setting up another options
				self.cfg_set('interface.useLB', use_left_button.get_active())
				self.cfg_set('interface.showPass', show_pass.get_active())
				by_user = group_user.get_active()
				old_by_user = self.cfg_get('interface.groupByUser')
				if by_user and not old_by_user or not by_user and old_by_user:
					self.cfg_set('interface.groupByUser', by_user)
					self.display_accounts()
					
				if need_update_data:
					self.save_accounts()
				self.write_config()
				
				break;				
			else:
				break
		dialog.destroy()
		
	def require_passw_dialog(self, message):
	
		wTree = gtk.glade.XML(self.gladefile, 'passw_dialog')
		dialog = wTree.get_widget("passw_dialog")
		wTree.get_widget('pass_mess').set_text(message)
		return_value = False
		response = dialog.run()
		if response == gtk.RESPONSE_OK:
			return_value = wTree.get_widget('req_password').get_text()
		dialog.destroy()
		return return_value

	def validate_input_pass(self, dialog, passw, rpassw):

		vpassw = passw.get_text()
		vrpassw = rpassw.get_text()
		minpasslen = 4
		if len(vpassw) < minpasslen:
			self.error_message(_("password require at least %s characters") % minpasslen, dialog)
			passw.set_text('')
			rpassw.set_text('')
			return False

		if (vpassw != vrpassw):
			self.error_message(_("password not confirmed. try again"), dialog)
			passw.set_text('')
			rpassw.set_text('')
			return False
			
		return vpassw
	
	def toggle_active(self, button, elements):
	
		active = button.get_active()
		for elem in elements:
			elem.set_sensitive(active)
		
	def status(self, status):
	
		context_id = self.statusbar.get_context_id("a")
		self.statusbar.pop(context_id)
		self.statusbar.push(context_id, status)
		
	def error_message(self, message, parent = None):
	
		if (None == parent):
			parent = self.window
			
		messagebox = gtk.MessageDialog(parent, 
			gtk.DIALOG_MODAL | gtk.DIALOG_DESTROY_WITH_PARENT,
		    gtk.MESSAGE_ERROR, gtk.BUTTONS_OK, _("error"))
		messagebox.format_secondary_text(message)
		messagebox.run()
		messagebox.destroy()
		
	def display_accounts(self):
	
		store = self.display_tree.get_model()
		store.clear()
		by_user = self.cfg_get('interface.groupByUser')
		for item in self.passwords.records:
			store.add_record(item, by_user)
			
	def on_tree_clicked(self, widget, event):

		if gtk.gdk.BUTTON3_MASK & event.get_state():
			self.on_tree_clicked_right(widget, event)
		elif gtk.gdk.BUTTON1_MASK & event.get_state():
			self.on_tree_clicked_left(widget, event)
			
	def on_tree_clicked_left(self, widget, event):
	
		if (self.cfg_get('interface.useLB')):
			self.on_copy_pass(widget)
		
	def on_icon_menu(self, icon, event_button, event_time):
	
		self.get_menu('context_icon').popup(None, None, gtk.status_icon_position_menu, event_button, event_time, icon)
	
	def on_tree_clicked_right(self, widget, event):
	
		tree, root, leaf = self.get_selected_record()
		if None == leaf:
			self.get_menu('context_root').popup(None, None, None, event.button, event.get_time())
		else:
			self.get_menu('context_leaf').popup(None, None, None, event.button, event.get_time())
			
	def get_menu(self, name):
		
		if self.menus.has_key(name):
			return self.menus[name]
		wTree = gtk.glade.XML(self.gladefile, name)
		wTree.signal_autoconnect({ 
			'on_reload': self.on_reload,
			'on_copy_pass': self.on_copy_pass,
			'on_copy_user': self.on_copy_user,
			'on_copy_account': self.on_copy_account,
			'on_edit_account': self.on_edit_account,
			'on_delete_account': self.on_delete_account,
			'on_add_leaf': self.on_add_leaf,
			'on_delete_group': self.on_delete_group,
			'on_activate': self.on_activate,
			'on_quit' : self.on_quit,
			'on_about' : self.on_about,
			'on_add_account' : self.on_add_account
		})
		menu = wTree.get_widget(name)
		self.menus[name] = menu
		return menu
		
	def get_selected_account(self):
	
		record = self.get_selected_record()
		if None == record:
			return None
		tree, root, leaf = record
		if None == leaf:
			return None
			
		return tree.get_value_account(leaf)
		
	def get_selected_record(self):
		
		selection = self.display_tree.get_selection()
		if 1 != selection.count_selected_rows():
			return None
			
		tree, item = selection.get_selected()
		parent = tree.iter_parent(item)
		if None == parent:
			return (tree, item, None)
		else:
			return (tree, parent, item)

	def on_quit(self, widget):

		gtk.main_quit()
		
	def on_about(self, widget):
	
		wTree = gtk.glade.XML(self.gladefile, 'aboutdialog')
		dialog = wTree.get_widget("aboutdialog")
		dialog.connect("response", lambda d, r: d.destroy())
		dialog.show()
	
	def confirm_action(self, message, target = None, parent = None):
	
		if (None == parent):
			parent = self.window
		
		messagebox = gtk.MessageDialog(parent, 
			gtk.DIALOG_MODAL | gtk.DIALOG_DESTROY_WITH_PARENT,
		    gtk.MESSAGE_QUESTION, gtk.BUTTONS_YES_NO, _("are you sure"))
		messagebox.format_secondary_text(message)
		response = messagebox.run()
		messagebox.destroy()
		return response == gtk.RESPONSE_YES

	def on_reload (self, widget):
	
		if self.load_accounts():
			self.display_accounts()
			self.status(_("accounts reloaded"))
			
	def on_toggle(self):
		
		if self.cfg_get('interface.groupByUser'):
			self.cfg_set('interface.groupByUser', False)
		else:
			self.cfg_set('interface.groupByUser', True)
		self.display_accounts()
		
	def on_add_leaf (self, widget):
	
		rec = self.get_selected_record()
		if None == rec:
			return
		tree, root, leaf = rec
		if None != leaf:
			return
		group = tree.get_value_string(root)
		if self.cfg_get('interface.groupByUser'):
			self.on_add_account(widget, None, group)
		else:
			self.on_add_account(widget, group)
		
	def on_delete_group (self, widget):
	
		rec = self.get_selected_record()
		if None == rec:
			return
		tree, root, leaf = rec
		if None != leaf:
			return
		group = tree.get_value_string(root)
		by_user = self.cfg_get('interface.groupByUser')
		if by_user:
			question = _("you want to delete user '%s'")
		else:
			question = _("you want to delete resource '%s'")
		if self.confirm_action(question % group):
			child = tree.iter_children(root)
			while child:
				account = tree.get_value_account(child)
				self.passwords.delete(account)
				nextchild = tree.iter_next(child)
				tree.remove(child)
				child = nextchild
			tree.remove(root)
			self.save_accounts()
			self.status(_("accounts deleted"))
		
	def on_delete_account (self, widget):

		rec = self.get_selected_record()
		if None == rec:
			return
		tree, root, leaf = rec
		if None == leaf:
			return
		acc = tree.get_value_account(leaf)
		if self.confirm_action(_("you want to delete account '%s'") % acc.nice_name()):
			if self.passwords.delete(acc):
				tree.remove(leaf)
				if not tree.iter_children(root):
					tree.remove(root)
				self.save_accounts()
				self.status(_("account deleted"))
				
	def on_delete (self):
		
		rec = self.get_selected_record()
		if None == rec:
			return
		tree, root, leaf = rec
		if None == leaf:
			self.on_delete_group(None)
		else:
			self.on_delete_account(None)
		
	def on_edit_account (self, widget):
	
		rec = self.get_selected_record()
		if None == rec:
			return
		tree, root, leaf = rec
		if None == leaf:
			return
		old_acc = tree.get_value_account(leaf)

		wTree = gtk.glade.XML(self.gladefile, 'add_account_dialog')
		dialog = wTree.get_widget("add_account_dialog")
		dialog.set_title(_("edit account"))
		wTree.get_widget('account_ok_label').set_text(_("update"))
		wTree.get_widget('account_ok').set_from_stock(gtk.STOCK_APPLY, gtk.ICON_SIZE_BUTTON)
		wTree.get_widget("resource").get_child().set_text(old_acc.resource)
		wTree.get_widget("login").get_child().set_text(old_acc.user)
		wTree.get_widget("password").set_text(old_acc.password)
		if old_acc.notes:
			wTree.get_widget("notes").get_buffer().set_text(old_acc.notes)
		if self.cfg_get('interface.showPass'):
			wTree.get_widget("password").set_visibility(True)
		self.bind_pass_gen(wTree)
		self.fill_combo(wTree)
		dialog.show()
		while True:
			response = dialog.run()
			if response == gtk.RESPONSE_OK:
				if self.edit_account(old_acc, dialog, wTree, rec):
					break;
			else:
				break
		dialog.destroy()
		
	def on_copy_pass(self, widget):

		acc = self.get_selected_account()
		if None != acc:
			clipboard = gtk.Clipboard()
			clipboard.set_text(acc.password)
			self.status(_("password copied into clipboard"))
		
	def on_copy_user(self, widget):

		acc = self.get_selected_account()
		if None != acc:
			clipboard = gtk.Clipboard()
			clipboard.set_text(acc.user)
			self.status(_("username copied into clipboard"))
		
	def on_copy_account(self, widget):

		acc = self.get_selected_account()
		if None != acc:
			clipboard = gtk.Clipboard()
			clipboard.set_text('%s@%s' % (acc.user, acc.get_domain()))
			self.status(_("account name copied into clipboard"))

	def load_config(self):
	
		try:
			cfg = minidom.parse(self.app_data_path + 'config.xml')
			for item in cfg.getElementsByTagName('opt'):
				name = item.getAttribute('name')
				ntype = item.getAttribute('type') or 'string'
				value = item.firstChild.nodeValue
				if 'bool' == ntype:
					value = 'True' == value
				elif 'int' == ntype:
					value = int(value)
				elif 'float' == ntype:
					value = float(value)
				self.config[str(name)] = value
		except:
			print 'Configuration file missing. Using default config.'

		self.cfg_default('interface.useLB', False)
		self.cfg_default('interface.showPass', False)
		self.cfg_default('interface.groupByUser', False)
		self.cfg_default('gpg.isActive', False)
		self.cfg_default('gpg.path', 'gpg')
	
	def write_config(self):
	
		cfg = minidom.getDOMImplementation().createDocument(None, 'config', None)
		for key, val in self.config.items():
			node = cfg.createElement('opt')
			cfg.firstChild.appendChild(node)
			node.setAttribute('name', key)
			if type(val) == bool:
				node.setAttribute('type', 'bool')
			elif type(val) == int:
				node.setAttribute('type', 'int')
			elif type(val) == float:
				node.setAttribute('type', 'float')
			node.appendChild(cfg.createTextNode(str(val)))
		
		try:
			f = open(self.app_data_path + 'config.xml', 'w')
			f.write(cfg.toxml('utf-8'))
			f.close()
		except:
			print "Error: Can't write configuration."

	def cfg_get(self, var, default = None):
	
		if self.config.has_key(var):
			return self.config[var]
		else:
			return default
	
	def cfg_set(self, var, val):
	
		if None == val:
			if self.config.has_key(var):
				del self.config[var]
		else:
			self.config[var] = val
	
	def cfg_default(self, var, val):
	
		if self.config.has_key(var):
			return self.config[var]
		else:
			self.config[var] = val
			return val
			
	def check_gnupg(self, path):
	
		gpg = GPG_Client(self.app_data_path + 'keys', path)
		return gpg.ping()
		
	def gpg_gen_key(self, password, gpg_path, dialog):
	
		wTree = gtk.glade.XML(self.gladefile, 'perform_operation')
		blockUI = wTree.get_widget("perform_operation")
		wTree.get_widget('operation').set_text(_("gpg key generation"))
		progressbar = wTree.get_widget('progressbar')
		thread = GpgKeyGenerator(password, gpg_path, self.app_data_path + 'keys')
		thread.start()
		while thread.isAlive():
			progressbar.pulse()
			gtk.main_iteration_do()
			time.sleep(0.01)
		res = thread.get_result()
		blockUI.destroy()
		if False == res:
			self.error_message(_("failed to create gpg key"), dialog)
			return False
		return res			
			
	def gpg_change_passw(self, key, newpassword, oldpassword, path, dialog):
	
		gpg = GPG_Client(self.app_data_path + 'keys', path)
		try:
			gpg.change_passw(key, newpassword, oldpassword)
			return True
		except GPG_Exception_Password:
			self.error_message(_("wrong password"), dialog)
		except GPG_Exception:
			self.error_message(_("failed to change password"), dialog)
		return False
		
	def gpg_encrypt(self, data, key):
	
		gpg = GPG_Client(self.app_data_path + 'keys', self.cfg_get('gpg.path'))
		try:
			return gpg.encrypt(data, key)
		except GPG_Exception_Seckey:
			self.cfg_set('gpg.key', None)
		except GPG_Exception:
			pass
		self.error_message(_("failed to encrypt data"))
		self.cfg_set('gpg.isActive', False)
		self.write_config()
		return False
			
	def gpg_decrypt(self, data, passphrase):
	
		gpg = GPG_Client(self.app_data_path + 'keys', self.cfg_get('gpg.path'))
		try:
			return gpg.decrypt(data, passphrase)
		except GPG_Exception_Password:
			self.error_message(_("wrong password"))
		except GPG_Exception:
			self.error_message(_("failed to encrypt data"))
		return False
		
	def check_folder(self, path, try_make = True, writable = False):
		path = path.rstrip('/')
		if os.access(path, os.F_OK):
			if not os.path.isdir(path):
				self.error_message(_("'%s' must be directory") % path)
				raise Exception("'%s' must be dir" % path)
			if writable and not os.access(path, os.W_OK):
				self.error_message(_("directory '%s' must be writable") % path)
				raise Exception("'%s' must be writable" % path)
			return
		
		if not try_make:
			self.error_message(_("directory '%s' not exists") % path)
			raise Exception("'%s' not exists" % path)
		
		dirname = os.path.dirname(path)
		if not os.path.isdir(dirname):
			self.error_message(_("'%s' must be directory") % dirname)
			raise Exception("'%s' must be dir" % dirname)
		if not os.access(dirname, os.W_OK):
			self.error_message(_("directory '%s' must be writable") % dirname)
			raise Exception("'%s' must be writable" % dirname)
		
		try:
			os.mkdir(path, 0700)
		except:
			self.error_message(_("failed to create directory '%s'") % path)
			raise Exception("Failed to create directory '%s'" % path)

	def check_file(self, path, writable = True):
	
		if os.access(path, os.F_OK):
			if not os.path.isfile(path):
				self.error_message(_("'%s' must be file") % path)
				raise Exception("'%s' must be file" % path)
			if writable and not os.access(path, os.W_OK):
				self.error_message(_("file '%s' must be writable") % path)
				raise Exception("'%s' must be writable" % path)
			return
		
		dirname = os.path.dirname(path)
		if not os.path.isdir(dirname):
			self.error_message(_("'%s' must be directory") % dirname)
			raise Exception("'%s' must be dir" % dirname)
		if not os.access(dirname, os.W_OK):
			self.error_message(_("directory '%s' must be writable") % dirname)
			raise Exception("'%s' must be writable" % dirname)

	def check_fs(self):
	
		self.check_folder(self.app_data_path)
		self.check_file(self.app_data_path + 'config.xml')
		self.check_file(self.app_data_path + 'accounts.xml')
		self.check_folder(self.app_data_path + 'keys')
		self.check_file(self.app_data_path + 'pubring.gpg')
		self.check_file(self.app_data_path + 'random_seed')
		self.check_file(self.app_data_path + 'secring.gpg')
		self.check_file(self.app_data_path + 'trustdb.gpg')
			
class GpgKeyGenerator(Thread):

	def __init__(self, password, gpg_path, home_path):
	
		Thread.__init__(self)
		self.password = password
		self.gpg_path = gpg_path
		self.home_path = home_path
		self.result = False
		
	def run(self):
        
		try:
			gpg = GPG_Client(self.home_path, self.gpg_path)
			self.result = gpg.gen_key(self.password)
		except Exception, e:
			print e
			
	def get_result(self):
	
		return self.result
		
class DisplayTreeModel(gtk.TreeStore):

	def __init__(self):
	
		# Display text, store text, record object, tooltip text
		gtk.TreeStore.__init__(self, gobject.TYPE_STRING, gobject.TYPE_STRING, gobject.TYPE_PYOBJECT, gobject.TYPE_STRING)
		self.set_sort_column_id(1, gtk.SORT_ASCENDING)
		
	def add_record(self, record, group_by_user = False):
		
		assert isinstance(record, PassStorageRecord)
		
		if group_by_user:
			v2 = record.resource
			v1 = record.user
		else:
			v1 = record.resource
			v2 = record.user
		
		parent = self.find_record(self.get_iter_first(), v1)
		leaf = None
		
		if None == parent:
			parent = self.append(None, None)
			self.set_root_value(parent, v1, record)
		else:
			leaf = self.find_record(self.iter_children(parent), v2)
			
		if None == leaf:
			leaf = self.append(parent, None)
			self.set_leaf_value(leaf, v2, record)
		
	def find_record(self, iterator, cmp_value):
	
		while iterator:
			value = self.get_value_string(iterator)
			if (value == cmp_value):
				return iterator
			iterator = self.iter_next(iterator)
		return None
		
	def get_value_string(self, iterator):
	
		return self.get_value(iterator, 1)
		
	def get_value_account(self, iterator):
	
		return self.get_value(iterator, 2)
	
	def set_root_value(self, root, value, account):
	
		markup = '<b>' +  value.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;') + '</b>'
		self.set(root, 0, markup)
		self.set(root, 1, value)
		
	def set_leaf_value(self, leaf, value, account):
	
		self.set(leaf, 0, value)
		self.set(leaf, 1, value)
		self.set(leaf, 2, account)
		if account.notes:
			self.set(leaf, 3, account.notes)
		else:
			self.set(leaf, 3, None)
		
class PassStorage(object):

	def __init__(self):
	
		self.records = []
		
	def add(self, record):
		
		assert isinstance(record, PassStorageRecord)
		self.records.append(record)
		
	def loadXml(self, xml):
		
		self.clear()
		try:
			if type(xml) == str:
				data = minidom.parseString(xml)
			elif not isinstance(xml, minidom.Document):
				return False
			
			for item in data.getElementsByTagName('account'):
				username = item.getAttribute('username')
				resource = item.getAttribute('resource')
				password = item.getAttribute('password')
				if item.hasChildNodes():
					notes = item.firstChild.nodeValue
				else:
					notes = None
				self.records.append(PassStorageRecord(resource, username, password, notes))
		except Exception, e:
			print 'Error while loading xml: ' + e.message
			return False
			
		return True
		
	def saveXml(self):
	
		accounts = minidom.getDOMImplementation().createDocument(None, 'accounts', None)
		for record in self.records:
			node = accounts.createElement('account')
			accounts.firstChild.appendChild(node)
			node.setAttribute('username', record.user)
			node.setAttribute('resource', record.resource)
			node.setAttribute('password', record.password)
			if record.notes:
				node.appendChild(accounts.createTextNode(str(record.notes)))
		
		return accounts.toxml('utf-8')
			
	def clear(self):
	
		del self.records[:]
		
	def find(self, record):
	
		try:
			return self.records.index(record)
		except:
			return -1
		
	def delete(self, record):
	
		index = self.find(record)
		if index != -1:
			self.records.remove(self.records[index])
			return True
		return False
			
	def __getitem__(self, index):
	
		return self.records[index]
			
	def __str__(self):
	
		strs = []
		for rec in self.records:
			strs.append(rec.__str__())
		return '[' + ', '.join(strs) + ']'
		
		
class PassStorageRecord(object):

	def __init__(self, resource, user, password = None, notes = None):
	
		self.resource = resource
		self.user = user
		self.password = password
		self.notes = notes
		
	def __eq__(self, compare_to):
	
		return 	isinstance(compare_to, PassStorageRecord) and \
				self.resource == compare_to.resource and \
				self.user == compare_to.user
				
	def is_clone_of(self, compare_to):
	
		return 	isinstance(compare_to, PassStorageRecord) and \
				self.resource == compare_to.resource and \
				self.user == compare_to.user and \
				self.password == compare_to.password and \
				self.notes == compare_to.notes
				
	def __str__(self):
		_str = self.user + ':' + self.password + '@' + self.get_domain()
		_proto = self.get_protocol()
		if None != _proto:
			return _proto + '://' + _str
		else:
			return _str
		
	def get_domain(self):
	
		parts = self.resource.split('://', 1)
		if len(parts) == 2:
			return parts[1]
		return parts[0]
	
	def get_protocol(self):
	
		parts = self.resource.split('://', 1)
		if len(parts) == 2:
			return parts[0]
		return None
	
	def nice_name(self):
	
		_str = self.user + '@' + self.get_domain()
		_proto = self.get_protocol()
		if None != _proto:
			return _proto + '://' + _str
		else:
			return _str

class GPG_Client(object):

	def __init__(self, home, command):
		
		self.homepath = home
		self.command = command
		
	def ping(self):
	
		cmd = '%s --version' % self.command
		proc = Popen(cmd, shell=True, stdin=PIPE, stdout=PIPE, stderr=PIPE)
		stdout, stderr = proc.communicate()
		firstline = stdout.split('\n', 2)[0]
		return 'gpg (GnuPG)' == firstline[0:11]
		
	def encrypt(self, data, key):

		cmd = '%s --status-fd 2 --no-tty --homedir "%s" --encrypt --armor --recipient %s' % (self.command, self.homepath, key)
		proc = Popen(cmd, shell=True, stdin=PIPE, stdout=PIPE, stderr=PIPE)
		stdout, stderr = proc.communicate(data)
		GPG_LogParserEncrypt(stderr)
		return stdout
			
	def decrypt(self, data, passphrase):
	
		cmd = 'gpg --status-fd 2 --no-tty --homedir "%s"  --batch --passphrase-fd 0 --decrypt' % (self.homepath)
		proc = Popen(cmd, shell=True, stdin=PIPE, stdout=PIPE, stderr=PIPE)
		stdout, stderr = proc.communicate("%s\n%s" % (passphrase, data))
		GPG_LogParserDecrypt(stderr)
		return stdout
		
		
	def gen_key(self, passphrase):

		current_host = socket.gethostname()
		current_user = os.getlogin()
		
		stdin  = "Key-Type: DSA\n"
		stdin += "Key-Length: 1024\n"
		stdin += "Subkey-Type: ELG-E\n"
		stdin += "Subkey-Length: 1024\n"
		stdin += "Expire-Date: 0\n"
		stdin += "Name-Real: %s\n" % (current_user)
		stdin += "Name-Email: %s@%s\n" % (current_user, current_host)
		stdin += "Passphrase: %s\n" % (passphrase)
		stdin += "%commit\n"

		cmd = 'gpg --status-fd 2 --no-tty --homedir "%s"  --gen-key --batch' % (self.homepath)
		proc = Popen(cmd, shell=True, stdin=PIPE, stdout=PIPE, stderr=PIPE)
		stdout, stderr = proc.communicate(stdin)
		res = GPG_LogParserGenKey(stderr)
		return res.result
			
	def change_passw(self, key, newpassword, oldpassword):
	
		stdin  = "password\n"
		stdin += "%s\n" % (oldpassword)
		stdin += "%s\n" % (newpassword)
		stdin += "save\n"
		
		cmd = 'gpg --status-fd 2 --no-tty --homedir "%s" --command-fd 0 --edit-key %s' % (self.homepath, key)
		proc = Popen(cmd, shell=True, stdin=PIPE, stdout=PIPE, stderr=PIPE)
		stdout, stderr = proc.communicate(stdin)
		GPG_LogParserChangePass(stderr)
		
class GPG_Exception(Exception):
	
	pass
	
class GPG_Exception_Password(GPG_Exception):
	
	pass
			
class GPG_Exception_Seckey(GPG_Exception):
	
	pass
			
class GPG_LogParser(object):

	def __init__(self, log):
	
		self.result = None
		self.parse_log(log)
		
	def handle_line(self, keyword, value):
	
		pass

	def parse_log(self, log):

		for line in log.split('\n'):
			if line[0:9] == '[GNUPG:] ':
				line = line[9:]
				L = line.split(None, 1)
				keyword = L[0]
				if len(L) > 1:
					value = L[1]
				else:
					value = ''
				if self.handle_line(keyword, value):
					return

		raise GPG_Exception
		
class GPG_LogParserEncrypt(GPG_LogParser):

	def handle_line(self, keyword, value):
	
		if 'END_ENCRYPTION' == keyword:
			return True
		
		elif 'INV_RECP' == keyword:
			raise GPG_Exception_Seckey
			
		return False
		
class GPG_LogParserDecrypt(GPG_LogParser):

	def handle_line(self, keyword, value):
		
		if 'DECRYPTION_OKAY' == keyword:
			return True
		
		elif 'DECRYPTION_FAILED' == keyword:
			raise GPG_Exception
			
		elif 'BAD_PASSPHRASE' == keyword:
			raise GPG_Exception_Password
			
		elif 'NO_SECKEY' == keyword:
			raise GPG_Exception_Seckey
			
		return False
		
class GPG_LogParserGenKey(GPG_LogParser):

	def handle_line(self, keyword, value):
	
		if 'KEY_CREATED' == keyword:
			ktype, kval = value.split()
			self.result = kval
			self.key_type = ktype
			return True
			
		elif 'KEY_NOT_CREATED' == keyword:
			raise GPG_Exception
			
		return False
			
class GPG_LogParserChangePass(GPG_LogParser):

	def __init__(self, log, message = None):

		self.pass_old_accepted = False
		self.pass_new_accepted = False
		GPG_LogParser.__init__(self, log)
	
	def handle_line(self, keyword, value):
	
		if 'BAD_PASSPHRASE' == keyword:
			raise GPG_Exception_Password
			
		elif 'GOOD_PASSPHRASE' == keyword:
			self.pass_old_accepted = True
			
		elif 'GOT_IT' == keyword:
			if self.pass_old_accepted:
				if self.pass_new_accepted:
					return True
				else:
					self.pass_new_accepted = True
			
		return False

if __name__ == "__main__":
	try:
		hwg = BreLock()
		gtk.main()
	except Exception, e:
		print e

