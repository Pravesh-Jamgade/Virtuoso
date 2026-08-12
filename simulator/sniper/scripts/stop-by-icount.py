# End ROI after x instructions (aggregated over all cores), with configurable x (default 1B) and optional warmup
# Combine with --no-cache-warming to use fast-forward rather than cache warmup
# Usage: -s stop-by-icount:30000000                            # Start in detailed, and end after 30M instructions
#        -s stop-by-icount:30000000 --roi                      # Start in warmup, switch to detailed at application ROI marker, and end after 30M instructions
#        -s stop-by-icount:30000000:100000000 --roi-script     # Start in cache-warmup, switch to detailed after 100M instructions, and run for 30M in detailed
#        -s stop-by-icount:30000000:roi+100000000 --roi-script # Start in cache-warmup, wait for application ROI, switch to detailed after 100M instructions, and run for 30M in detailed
import sys
if not hasattr(sys, 'argv') or not sys.argv:
  sys.argv = [ 'stop-by-icount.py', '1000000000' ]
import sim


class StopByIcount:


  def get_stat_safe(self, component, metric, core=None):
    try:
      if core is not None:
        return float(sim.stats.get(component, core, metric))
      total = 0.0
      ncores = int(sim.config.get('general/total_cores'))
      for c in range(ncores):
        try:
          total += float(sim.stats.get(component, c, metric))
        except Exception:
          pass
      return total
    except Exception:
      return 0.0

  def get_cache_hit_rate(self, component):
    variations = [component]
    if component == 'L3':
      variations += ['l3_cache', 'L3-0', 'l3_cache-0', 'LLC', 'LLC-0', 'nuca', 'nuca-0', 'L3_cache']
    elif component == 'L1-I':
      variations += ['L1-I-0', 'l1-i']
    elif component == 'L1-D':
      variations += ['L1-D-0', 'l1-d']
    elif component == 'L2':
      variations += ['L2-0', 'l2-cache', 'l2']
    
    loads = 0.0
    stores = 0.0
    load_misses = 0.0
    store_misses = 0.0
    
    for var in variations:
      loads = self.get_stat_safe(var, 'tloads')
      stores = self.get_stat_safe(var, 'tstores')
      load_misses = self.get_stat_safe(var, 'tload-misses')
      store_misses = self.get_stat_safe(var, 'tstore-misses')
      if loads > 0 or stores > 0:
        break
        
    accesses = loads + stores
    misses = load_misses + store_misses
    
    if accesses > 0:
      return (accesses - misses) / float(accesses)
    else:
      return 1.0

  def log_heartbeat(self, icount, icount_delta):
    ncores = int(sim.config.get('general/total_cores'))
    instrs = float(icount - self.ninstrs_start)
    if instrs < 0:
      instrs = 0.0
        
    time_fs = float(sim.stats.time())
    time_ns = time_fs / 1e6
    
    freq_mhz = float(sim.dvfs.get_frequency(0))
    cycles = time_fs * freq_mhz / 1e9
    ipc = instrs / cycles if cycles > 0 else 0.0
    
    pagefaults = 0.0
    for core in range(ncores):
      pagefaults += self.get_stat_safe('mmu_%d' % core, 'page_faults')
      pagefaults += self.get_stat_safe('mmu_base_%d' % core, 'page_faults')
      pagefaults += self.get_stat_safe('mmu_dmt_%d' % core, 'page_faults')
      pagefaults += self.get_stat_safe('mmu_virt_%d' % core, 'page_faults')
      pagefaults += self.get_stat_safe('mmu', 'page_faults', core)
        
    stlb_misses = 0.0
    stlb_names = ['stlb', 'stlb-0', 'stlb_0', 'L2_TLB', 'L2_TLB-0', 'stlb_cache']
    for name in stlb_names:
      stlb_misses += self.get_stat_safe(name, 'misses')
      stlb_misses += self.get_stat_safe(name, 'tload-misses')
      stlb_misses += self.get_stat_safe(name, 'tstore-misses')
        
    dram_accesses = self.get_stat_safe('dram', 'reads') + self.get_stat_safe('dram', 'writes')
    
    l1_i_hit_rate = self.get_cache_hit_rate('L1-I')
    l1_d_hit_rate = self.get_cache_hit_rate('L1-D')
    l2_hit_rate = self.get_cache_hit_rate('L2')
    llc_hit_rate = self.get_cache_hit_rate('L3')
    
    log_line = (
      "[HEARTBEAT] Icount: %d | ROI Insts: %d | Time: %.3f ms | IPC: %.4f | "
      "Pagefaults: %d | STLB Misses: %d | DRAM Accesses: %d | "
      "L1-I HitRate: %.4f | L1-D HitRate: %.4f | L2 HitRate: %.4f | LLC HitRate: %.4f\n"
    ) % (
      icount, int(instrs), time_ns / 1e6, ipc,
      int(pagefaults), int(stlb_misses), int(dram_accesses),
      l1_i_hit_rate, l1_d_hit_rate, l2_hit_rate, llc_hit_rate
    )
    
    output_dir = sim.config.get('general/output_dir')
    with open(output_dir + '/heartbeat.log', 'a') as f_log:
      f_log.write(log_line)
    
    print(log_line.strip())

  def _min_callback(self):
      return min(self.ninstrs_start if self.ninstrs_start else float('inf'), self.ninstrs, self.min_ins_global)


  def setup(self, args):
    self.magic = sim.config.get_bool('general/magic')
    self.min_ins_global = int(sim.config.get('core/hook_periodic_ins/ins_global'))
    self.wait_for_app_roi = False
    self.verbose = True
    args = dict(enumerate((args or '').split(':')))
    self.ninstrs = int(args.get(0, 1e9))
    start = args.get(1, None)
    roirelstart = False
    # Make the start input value canonical
    output_dir = sim.config.get('general/output_dir')
    with open(output_dir + '/heartbeat.txt', 'w') as f_heartbeat:
        f_heartbeat.write("Heartbeats are written to this file\n")
    if start == '':
      start = None
    roiscript = sim.config.get_bool('general/roi_script')

    if start == None and not roiscript:
      if self.magic:
        self.roi_rel = True
        self.ninstrs_start = 0
        self.inroi = False
        print('[STOPBYICOUNT] Waiting for application ROI')
      else:
        self.roi_rel = True
        self.ninstrs_start = 0
        self.inroi = True
        print('[STOPBYICOUNT] Starting in ROI (detail)')
    else:
      if self.magic:
        print('[STOPBYICOUNT] ERROR: Application ROIs and warmup cannot be combined when using --roi')
        print('[STOPBYICOUNT] Use syntax: -s stop-by-icount:NDETAIL:roi+NWARMUP --roi-script')
        sim.control.abort()
        self.done = True
        return
      if not roiscript:
        print('[STOPBYICOUNT] ERROR: --roi-script is not set, but is required when using a start instruction count. Aborting')
        sim.control.abort()
        self.done = True
        return
      if start == None:
        # If start == None, then an explicit start has not been set, but --roi-script has also been enabled.
        # Therefore, set to start on the next instruction callback
        print('[STOPBYICOUNT] WARNING: No explicit start instruction count was set, but --roi-script is set')
        print('               WARNING: Starting detailed simulation on the next callback, %d instructions' % self.min_ins_global)
        print('               WARNING: To start from the beginning, do not use --roi-script with a single stop argument')
        start = self.min_ins_global
      if start.startswith('roi+'):
        self.ninstrs_start = int(start[4:])
        self.roi_rel = True
        self.wait_for_app_roi = True
        print('[STOPBYICOUNT] Starting %s instructions after ROI begin' % self.ninstrs_start)
      else:
        self.ninstrs_start = int(start)
        self.roi_rel = False
        print('[STOPBYICOUNT] Starting after %s instructions' % self.ninstrs_start)
      self.inroi = False
    print('[STOPBYICOUNT] Then stopping after simulating %s instructions in detail' % ((self.roi_rel and 'at least ' or '') + str(self.ninstrs)))
    self.done = False
    with open(output_dir + '/heartbeat.log', 'w') as f_log:
        f_log.write("Heartbeat Log Started\n")
    self.heartbeat_interval = max(1, self.ninstrs // 10)
    sim.util.EveryIns(self.heartbeat_interval, self.log_heartbeat, roi_only = True)
    sim.util.EveryIns(self._min_callback(), self.periodic, roi_only = (start == None))


  def hook_application_roi_begin(self):
    if self.wait_for_app_roi:
      print('[STOPBYICOUNT] Application at ROI begin, fast-forwarding for', self.ninstrs_start, 'more instructions')
      self.wait_for_app_roi = False
      self.ninstrs_start = sim.stats.icount() + self.ninstrs_start


  def hook_roi_begin(self):
    if self.magic:
      self.ninstrs_start = sim.stats.icount()
      self.inroi = True
      print('[STOPBYICOUNT] Application ROI started, now simulating', self.ninstrs, 'in detail')
      output_dir = sim.config.get('general/output_dir')
      with open(output_dir + '/heartbeat.txt', 'a') as f_heartbeat:
        f_heartbeat.write("Application ROI started, now simulating %s in detail\n" % self.ninstrs)


  def periodic(self, icount, icount_delta):
    if not self.wait_for_app_roi and not self.done and icount < (self.ninstrs + self.ninstrs_start):
      sim.control.set_progress(icount / float(self.ninstrs + self.ninstrs_start + 1))

    if self.done:
      return
    if self.verbose:
      print('[STOPBYICOUNT] Periodic at', icount, ' delta =', icount_delta)
      heartbeat = '[STOPBYICOUNT] Periodic at %s delta = %s\n' % (icount, icount_delta)
      #write the heartbeat to the file
      output_dir = sim.config.get('general/output_dir')
      with open(output_dir + '/heartbeat.txt', 'a') as f_heartbeat:
        f_heartbeat.write(heartbeat)

    if self.inroi and icount > (self.ninstrs + self.ninstrs_start):
      print('[STOPBYICOUNT] Ending ROI after %s instructions (%s requested)' % (icount - self.ninstrs_start, self.ninstrs))
      sim.control.set_roi(False)
      self.inroi = False
      self.done = True
      sim.control.abort()
    elif not self.inroi and not self.wait_for_app_roi and icount > self.ninstrs_start:
      print('[STOPBYICOUNT] Starting ROI after %s instructions' % icount)
      sim.control.set_roi(True)
      self.inroi = True


sim.util.register(StopByIcount())
