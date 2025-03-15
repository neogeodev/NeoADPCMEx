from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtCore import QSize, Qt, pyqtSignal
from PyQt5.QtWidgets import QWidget

import time

class waveCanvas(QWidget):
	clicked = pyqtSignal(int, bool)
	scrolled = pyqtSignal(int)

	#def __init__(self, parent = None):
	def __init__(self, sampleCount, showCursor, enableScrolling):
		QWidget.__init__(self)
		self.setMouseTracking(True)
		self.vfile = None
		self.hoverCursor = 0
		self.setXDelta()
		self.blockView = False	# Show ADPCM blocks boundaries on background
		self.sampleStart = 0	# On which sample to start (left)
		self.sampleCount = sampleCount	# How many samples to display left to right, in given width
		self.enableScrolling = enableScrolling
		self.showCursor = showCursor
		self.cursor = 0
		self.highlight = [0, 0]

	def setSampleCount(self, sampleCount):
		self.sampleCount = sampleCount
		self.setXDelta()
		self.genWaveform()

	def setSampleStart(self, sampleStart):
		if sampleStart > 0 and sampleStart < self.vfile.pcm_size - self.sampleCount:
			self.sampleStart = sampleStart
		else:
			self.sampleStart = 0
		self.genWaveform()

	def setCursor(self, cursor):
		if cursor > 0 and cursor < self.vfile.pcm_size:
			self.cursor = cursor
			self.repaint()

	def setHighlight(self, highlight):
		self.highlight = highlight
		self.repaint()

	def setVfile(self, vfile):
		self.vfile = vfile
		if self.sampleCount == 0:
			self.sampleCount = self.vfile.pcm_size	# Set to entire waveform by default
		self.setXDelta()
		self.genWaveform()

	def setXDelta(self):
		if self.vfile:
			self.XDelta = self.sampleCount / self.size().width()

	def enableBlockView(self, blockView):
		self.blockView = blockView

	def resizeEvent(self, e):
		print("Resized !")
		self.setXDelta()
		self.genWaveform()

	def mouseMoveEvent(self, e):
		# Refresh hover cursor
		self.hoverCursor = e.pos().x()
		self.repaint()

	def mouseReleaseEvent(self, e):
		if self.vfile:
			# Emit clicked signal with [sample number, right click]
			self.clicked.emit(int(self.sampleStart + e.pos().x() * self.XDelta), True if e.button() == QtCore.Qt.RightButton else False)
	
	def wheelEvent(self, e):
		if self.enableScrolling and self.vfile:
			delta = e.angleDelta().y() * 4	# Arbitrary
			#print(delta)
			self.setSampleStart(self.sampleStart + delta)
			self.scrolled.emit(self.sampleStart)

	def keyPressEvent(self, keyEvent):
		if self.enableScrolling:
			delta = 2048	# Arbitrary
			if keyEvent.key() == Qt.Key_Left:
				self.setSampleStart(self.sampleStart - delta)
			elif keyEvent.key() == Qt.Key_Right:
				self.setSampleStart(self.sampleStart + delta)
			self.scrolled.emit(self.sampleStart)

	def genWaveform(self, start=0, end=0):
		# Generate waveform display data for fast painting
		# start and end parameters (in samples) allow partial refreshing to speed things up
		if not self.vfile:
			return

		#debug = time.time()	# PROFILING

		# Widget size
		width = self.size().width()
		height = self.size().height()
		center = height // 2
		vRatio = height / 65535.0	# Depends on PCM data format

		# One entry for each column (x pixel)
		if end == 0:
			start = 0
			end = self.vfile.pcm_size
			self.waveformData = width * [0]	# Regen everything
		
		colStart = self.sampleStart
		for column in range(width):
			colEnd = colStart + self.XDelta
			# Find out if this column needs to be generated, true if there's any overlap with the [start, end] range
			if ((colStart >= start and colStart < end) or
				(colEnd >= start and colEnd < end)):
				# Find min and max values in range of samples covered by one pixel
				rangeMin = 32767
				rangeMax = -32768
				if colStart < 0:	# Shouldn't happen
					rangeMin = 0
					rangeMax = 0
				else:
					for s in range(int(colStart), int(colEnd)):	# This will produce equal rangeMin and rangeMax if XDelta == 1
						value = self.vfile.pcm_data[s]
						if value > rangeMax:
							rangeMax = value
						if value < rangeMin:
							rangeMin = value
				rangeMin *= vRatio
				rangeMax *= vRatio
				# waveformData is a list of [min, max, mean] adjusted to widget height for fast plotting
				self.waveformData[column] = [center - rangeMin, center - rangeMax, center - ((rangeMin + rangeMax) / 2)]
			colStart += self.XDelta
		#print("genWaveform:", time.time() - debug)	# PROFILING
		self.repaint()

	def paintEvent(self, e):
		if self.vfile:
			stripeColors = [QtGui.QColor('white'), QtGui.QColor(240, 240, 240)]
			painter = QtGui.QPainter(self)
			width = self.size().width()
			height = self.size().height()

			# Block stripes, if enabled
			if self.blockView:
				blockColorAlt = 0 if self.sampleStart & 512 else 1	# Start color
				blockCount = (self.sampleCount // 2) >> 8
				blockOffset = int((512 - (self.sampleStart & 511)) / self.XDelta)
				blockWidth = width / blockCount

				if blockOffset:
					painter.fillRect(0, 0, blockOffset, height, stripeColors[blockColorAlt ^ 1])

				for x in range(blockCount):
					painter.fillRect(int(blockOffset), 0, int(blockWidth), height, stripeColors[blockColorAlt])
					blockOffset += blockWidth
					blockColorAlt ^= 1

			# Waveform view
			pen = QtGui.QPen(QtGui.QColor('darkGray'))
			painter.setPen(pen)
			for x in range(width):
				painter.drawLine(x, int(self.waveformData[x][0]), x, int(self.waveformData[x][1]))

			# Waveform mean view
			pen = QtGui.QPen(QtGui.QColor('black'))
			painter.setPen(pen)
			for x in range(width):
				painter.drawPoint(x, int(self.waveformData[x][2]))

			# Zero line
			pen.setColor(QtGui.QColor('blue'))
			painter.setPen(pen)
			painter.drawLine(0, height // 2, width, height // 2)

			# Reset markers
			pen_a = QtGui.QPen(QtGui.QColor('darkRed'))
			pen_b = QtGui.QPen(QtGui.QColor('darkGreen'))
			for reset in self.vfile.resets:
				v = ((reset[0] * 2) << 8) - self.sampleStart
				if v >= 0 and v < self.sampleStart + self.sampleCount:
					x_pos = int(v / self.XDelta)
					painter.setPen(pen_b if reset[1] else pen_a)
					painter.drawLine(x_pos, 0, x_pos, height)

			# Cursor
			if self.showCursor:
				pen.setColor(QtGui.QColor('green'))
				painter.setPen(pen)
				pixelCursor = int(self.cursor / self.XDelta)
				painter.drawLine(pixelCursor, 0, pixelCursor, height)

			# Hover cursor
			pen.setColor(QtGui.QColor('red'))
			painter.setPen(pen)
			painter.drawLine(self.hoverCursor, 0, self.hoverCursor, height)
			
			# Highlight
			if self.highlight != [0, 0]:
				painter.setCompositionMode(QtGui.QPainter.CompositionMode_Difference)
				painter.fillRect(int(self.highlight[0] / self.XDelta), 0, int(self.highlight[1] / self.XDelta), height, QtGui.QColor('white'))
