# V ROM object with raw and decoded PCM buffers
# Decoding code from MAME

class Vfile():
	def __init__(self, filepath):
		step_size = [
			 16,  17,   19,   21,   23,   25,   28,
			 31,  34,   37,   41,   45,   50,   55,
			 60,  66,   73,   80,   88,   97,  107,
			118, 130,  143,  157,  173,  190,  209,
			230, 253,  279,  307,  337,  371,  408,
			449, 494,  544,  598,  658,  724,  796,
			876, 963, 1060, 1166, 1282, 1411, 1552
		]
		self.step_a_adj = [ -1, -1, -1, -1, 2, 5, 7, 9 ]
		self.step_b_adj = [ 57, 57, 57, 57, 77, 102, 128, 153 ]

		# Precalc ADPCM-A table
		# For each of the 49 steps, compute the delta value represented by each nibble
		self.jedi_table = 16 * 49 * [0]
		for step in range(49):
			for nib in range(16):
				value = int((2 * (nib & 7) + 1) * step_size[step] / 8)
				self.jedi_table[step * 16 + nib] = -value if (nib & 8) else value
		#print(jedi_table)

		with open(filepath, "rb") as f_in:
			self.raw_data = bytearray(f_in.read())

		self.resets = [[0, 0]]	# Format: [ADPCM block number, type (0:A, 1:B)]
		self.raw_size_bytes = len(self.raw_data)
		self.raw_size_blocks = self.raw_size_bytes // 256	# YM2610 ADPCM blocks
		self.pcm_size = self.raw_size_bytes * 2				# Two PCM samples for one ADPCM byte containing 2 codes
		self.pcm_data = self.pcm_size * [0]

		self.curType = 0
		self.resetState()
	
	def resetState(self):
		self.acc = 0
		self.decstep = 0
		self.adpcmb_step = 127	# STEP_MIN

	def adpcmADec(self, nibble):
		self.acc += self.jedi_table[(self.decstep << 4) + nibble]
		self.acc &= 0xfff		# Accumulator wraps
		if self.acc & 0x800:
			self.acc |= ~0xfff	# Sign extend if negative
		self.decstep += self.step_a_adj[nibble & 7]
		if (self.decstep < 0):
			self.decstep = 0
		if (self.decstep > 48):
			self.decstep = 48

		return self.acc << 4	# Returns s16 sample

	def adpcmBDec(self, nibble):
		delta = ((2 * (nibble & 7) + 1) * self.adpcmb_step) >> 3
		delta = -delta if (nibble & 8) else delta

		self.acc += delta
		if (self.acc < -32768):
			self.acc = -32768
		if (self.acc > 32767):
			self.acc = 32767

		#if self.acc & 0x8000:
		#	self.acc |= ~0xffff	# Sign extend if negative
		self.adpcmb_step = (self.adpcmb_step * self.step_b_adj[nibble & 7]) >> 6
		if (self.adpcmb_step < 127):	# STEP_MIN
			self.adpcmb_step = 127
		if (self.adpcmb_step > 24576):	# STEP_MAX
			self.adpcmb_step = 24576

		return self.acc		# Returns s16 sample

	# Get reset index from block number
	def findReset(self, blockNumber):
		i = 0
		for reset in self.resets:
			if reset[0] == blockNumber:
				return i
			i += 1
		return None

	def toggleReset(self, blockNumber, ab):
		updateNew = False

		# See if blockNumber is already in resets list
		found = self.findReset(blockNumber)

		if found != None:
			# If click of same type: remove reset
			# There HAS to be a reset at the very start of the file, never remove it
			if self.resets[found][1] == ab and blockNumber != 0:
				# Only need to update decoded data from the previous reset to next one
				self.resets.sort(key = lambda e: e[0])

				i = self.findReset(blockNumber)
				if i - 1 >= 0:
					start = self.resets[i - 1][0]	# Start is previous reset
				else:
					start = 0 						# Start is first block
				if i + 1 < len(self.resets):
					end = self.resets[i + 1][0]		# End is next reset
				else:
					end = self.raw_size_blocks		# End is last block
	
				del self.resets[i]
	
				# DEBUG
				print("Removed reset at block {:d}".format(blockNumber))
			else:
				# Otherwise: udpate reset type
				self.resets[found][1] = ab
				updateNew = True
		else:
			# Add reset
			self.resets.append([blockNumber, ab])
			print("Added reset at block {:d}".format(blockNumber))	# DEBUG
			updateNew = True

		if updateNew:
			# Only need to update decoded data from new or updated reset to next one
			self.resets.sort(key = lambda e: e[0])

			i = self.findReset(blockNumber)
			start = blockNumber					# Start is new reset
			if i + 1 < len(self.resets):
				end = self.resets[i + 1][0]		# End is next reset
			else:
				end = self.raw_size_blocks		# End is last block

		# DEBUG
		#for reset in self.resets:
		#	print("Reset at {:d}".format(reset[0]))

		self.decode(start, end, self.resets)
		return [start, end]

	def decode(self, startBlock, endBlock, resets = [0, 0]):
		# Cap start/stop
		if startBlock < 0:
			startBlock = 0
		if endBlock >= self.raw_size_blocks:
			endBlock = self.raw_size_blocks

		self.resets.sort(key = lambda e: e[0])	# Lowest to highest position

		# DEBUG
		print("Decoding from block %d to %d" % (startBlock, endBlock))

		i = startBlock << 8		# ADPCM data position
		j = i * 2				# PCM data position
		for block in range(startBlock, endBlock):
			found = self.findReset(block)	# This could be simplified since resets are now sorted ?
			if found != None:
				self.curType = self.resets[found][1]
				self.resetState()
				# DEBUG
				print("Reset at block %d, type %s" % (block, "B" if self.curType else "A"))

			if self.curType:
				for s in range(256):
					byte = self.raw_data[i]
					self.pcm_data[j] = self.adpcmBDec(byte >> 4)
					self.pcm_data[j + 1] = self.adpcmBDec(byte & 15)
					i += 1
					j += 2
			else:
				for s in range(256):
					byte = self.raw_data[i]
					self.pcm_data[j] = self.adpcmADec(byte >> 4)
					self.pcm_data[j + 1] = self.adpcmADec(byte & 15)
					i += 1
					j += 2
