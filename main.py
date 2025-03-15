# GUI tool for extracting ADPCM samples from V ROMs by manually setting boundaries
# Furrtek 2025

# On overiew:
#	Left click sets cursor for the detail view and sample playback
# On detail view:
#	Left click toggles an ADPCM-A reset
#	Right click toggles an ADPCM-B reset
#	Mouse scroll moves cursor
#	Left and right keys moves cursor faster
# Playback reads the sample in which the cursor falls, with a 5s duration limit
# Save saves a .csv with the boundary data for future reloading
# Export saves a .raw s16 mono audio file and individual .wav files for each sample

# TODO: Auto helper that detects sudden amplitude changes

# See https://github.com/mamedev/mame/blob/master/3rdparty/ymfm/src/ymfm_adpcm.cpp
# UI waveform navigation and display, reset placement, loading/saving works fine
# ADPCM A/B decoding is pretty good but there's some drifting, step table incorrect or Python porting problem ?

# One ADPCM byte = two 4-bit ADPCM samples = two u8 PCM samples
# The YM2610 works on 256-byte groups of ADPCM data (512 samples)
# The waveCanvas widgets show PCM waveforms from a Vfile
# They're set up with a sampleCount (number of samples to show along width), and a sampleStart (left position)

import sys
import os
import wave
import time
import struct
from vfile import Vfile
from wavecanvas import waveCanvas
import pyaudio

from PyQt5 import QtCore, QtGui, QtWidgets	#, uic
from PyQt5.QtCore import QSize, Qt, pyqtSignal
from PyQt5.QtWidgets import QWidget, QApplication, QMainWindow, QPushButton, QVBoxLayout, QFileDialog

DETAILWIDTH = 8192	# DETAILWIDTH // 2 PCM samples around cursor
SAMPLERATE = 18518	# ADPCM-A samplerate

class MainWindow(QMainWindow):
	def __init__(self):
		super().__init__()

		self.vfile = None

		self.setWindowTitle("YM2610 ADPCM extractor")
		self.setFixedSize(QSize(1024, 600))
		layout = QVBoxLayout()

		self.waveform_ov = waveCanvas(0, True, False)			# Overview
		self.waveform_ov.clicked.connect(self.clickedOV)
		layout.addWidget(self.waveform_ov)

		self.waveform = waveCanvas(DETAILWIDTH, False, True)	# Detail view
		self.waveform.enableBlockView(True)
		self.waveform.clicked.connect(self.clickedDetail)
		self.waveform.scrolled.connect(self.scrolledDetail)
		self.waveform.setFocusPolicy(QtCore.Qt.WheelFocus)
		layout.addWidget(self.waveform)

		button = QPushButton("Open")
		button.clicked.connect(self.openFile)
		layout.addWidget(button)

		button2 = QPushButton("Save")
		button2.clicked.connect(self.saveCSV)
		layout.addWidget(button2)

		button3 = QPushButton("Export")
		button3.clicked.connect(self.export)
		layout.addWidget(button3)

		button4 = QPushButton("Play")
		button4.clicked.connect(self.play)
		layout.addWidget(button4)

		widget = QWidget()
		widget.setLayout(layout)

		self.setCentralWidget(widget)

	def closeEvent(self, event):
		if self.vfile:
			self.saveCSV()	# Save on exit
			event.accept()

	def clickedOV(self, x):
		#print("OV clicked at PCM sample %d" % x)
		self.waveform_ov.setCursor(x)
		self.waveform.setSampleStart(x - (DETAILWIDTH // 2))

	def clickedDetail(self, x, button):
		#print("Detail clicked at PCM sample %d" % x)
		block = (x >> 1) >> 8	# All samples are aligned to 256-byte blocks, so resets can only occur on those boundaries

		start, end = self.vfile.toggleReset(block, 1 if button else 0)
		self.waveform.genWaveform()		# Regen everything in detail view, already fast enough
		self.waveform_ov.genWaveform(start << 9, end << 9)	# Regen only updated region in overall view
		
	def scrolledDetail(self, x):
		self.waveform_ov.setCursor(x + (DETAILWIDTH // 2))

	def openFile(self):
		file_dialog = QFileDialog(self)
		file_dialog.setWindowTitle("Open V ROM file")
		file_dialog.setFileMode(QFileDialog.FileMode.ExistingFile)
		file_dialog.setViewMode(QFileDialog.ViewMode.Detail)
		file_dialog.setNameFilters(["V ROM files (*.*)"])

		if not file_dialog.exec():
			return

		filePath = file_dialog.selectedFiles()[0]
		fileSize = os.path.getsize(filePath)

		if fileSize > 2**24:
			print("Selected file exceeds 16MB")
			return

		fileName = os.path.basename(filePath)
		self.fileStem = os.path.splitext(fileName)[0]
		self.vfile = Vfile(filePath)

		fname = self.fileStem + ".csv"
		if os.path.isfile(fname):
			print("Found a CSV file for %s" % fileName)
			with open(fname, "r") as f_in:			# Load CSV file
				for line in f_in:
					line = line.replace("\n",'')
					if line != "":
						v = line.split(',')
						if len(v) == 1:				# Only block number present, assume ADPCM-A
							self.vfile.resets.append([int(v[0]), 0])
						elif len(v) == 2:			# Block number present and type
							self.vfile.resets.append([int(v[0]), int(v[1])])
		self.vfile.resets.append([self.vfile.raw_size_blocks, 0])	# End of file reset as marker

		self.vfile.decode(0, self.vfile.raw_size_blocks)	# Decode entire file

		self.waveform_ov.setVfile(self.vfile)
		self.waveform.setVfile(self.vfile)

	def saveCSV(self):
		print("Saving")

		with open(self.fileStem + ".csv", "w") as f_out:	# Save reset points
			for reset in self.vfile.resets[1:-1]:	# Don't save the very first reset (implicit), not the last one (EOF marker)
				f_out.write(str(reset[0]) + ',' + str(reset[1])+ "\n")

	def export(self):
		if not self.vfile:
			return

		# Single raw s16 PCM file
		#self.vfile.decode(0, self.vfile.raw_size_blocks)	# Re-decode entire file with resets to make sure pcm_data is up to date
		with open(self.fileStem + ".raw", "wb") as f_out:
			for sample in self.vfile.pcm_data:
				f_out.write(sample.to_bytes(2, byteorder='little', signed=True))

		# Multiple wave files
		resetCount = len(self.vfile.resets)
		for i, reset in enumerate(self.vfile.resets):
			fname = self.fileStem + "_{:03d}.wav".format(i)
			with wave.open(fname, "w") as f:
				f.setnchannels(1)
				f.setsampwidth(2)
				f.setframerate(SAMPLERATE)
				start = reset[0] << 9
				if i < resetCount - 1:
					stop = self.vfile.resets[i + 1][0] << 9	# Up to next reset
				else:
					stop = len(self.vfile.pcm_data)	# Up to end
				#print(start, stop)
				f.writeframes(struct.pack("<%sh" % (stop - start), *self.vfile.pcm_data[start:stop]))
		print("Export OK")

	def play(self):
		if not self.vfile:
			return

		# Play sample between resets where detail cursor is
		self.vfile.resets.sort(key = lambda e: e[0])	# Make sure resets are sorted

		# Find index of reset just before cursor
		cursor = self.waveform_ov.cursor
		#print("Cursor ", cursor)
		for i, reset in enumerate(self.vfile.resets):
			#print("Reset ", i, reset[0] << 9)
			if (reset[0] << 9) > cursor:
				break

		self.playPos = self.vfile.resets[i - 1][0] << 9
		duration = (self.vfile.resets[i][0] << 9) - self.playPos

		if duration > SAMPLERATE * 5:	# Cap max duration to 5s
			duration = SAMPLERATE * 5
		self.playEnd = self.playPos + duration
		
		self.waveform_ov.setHighlight([self.playPos, duration])

		stream = p.open(format=pyaudio.paInt16, channels=1, rate=SAMPLERATE, output=True, stream_callback=self.playCallback)
		while stream.is_active():
			time.sleep(0.1)
		stream.close()

	def playCallback(self, in_data, frame_count, time_info, status):
		samples = self.vfile.pcm_data[self.playPos:self.playPos + frame_count]
		buf = bytearray()
		for sample in samples:
			buf += sample.to_bytes(2, byteorder='little', signed=True)
		self.playPos += frame_count
		if self.playPos < self.playEnd:
			flag = pyaudio.paContinue
		else:
			flag = pyaudio.paComplete

		return (bytes(buf), flag)

app = QApplication(sys.argv)

p = pyaudio.PyAudio()

window = MainWindow()
window.show()

app.exec()

p.terminate()

exit()
