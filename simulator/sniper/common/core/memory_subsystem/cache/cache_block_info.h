#ifndef __CACHE_BLOCK_INFO_H__
#define __CACHE_BLOCK_INFO_H__

#include "fixed_types.h"
#include "cache_state.h"
#include "cache_base.h"

struct PTEFootprintStats {
	bool is_pte_block = false;
	uint8_t page_table_level = 0;
	// PTEs accessed while this block is resident
	uint8_t footprint = 0;
	// PTE responsible for initially bringing the block
	uint8_t initial_pte_index = 0;
	// Number of PTW accesses to this block
	uint32_t total_pte_accesses = 0;
	// Number of distinct PTEs used
	uint8_t distinct_pte_count = 0;
	// Cache replacement state observations
	int install_lru_position = 0;
	int last_change_lru_position = -1;
	int max_change_lru_position = -1;
	// Time and access sequence information
	uint64_t install_cycle = 0;
	uint64_t last_access_cycle = 0;
	uint64_t last_footprint_change_cycle = 0;
	uint64_t install_access_id = 0;
	uint64_t last_footprint_change_access_id = 0;
	// Footprint when last changed
	uint8_t footprint_after_last_change = 0;
	// Number of cache hits after footprint stopped growing
	uint32_t accesses_after_last_change = 0;

	uint64_t block_instance_id = 0;
	IntPtr block_address = 0;
};

class CacheBlockInfo
{
public:
	enum option_t
	{
		PREFETCH,
		WARMUP,
		NUM_OPTIONS
	};

	enum block_type_t
	{
		PAGE_TABLE_DATA	= 0, // Page table data (e.g., PTEs for data pages)
		PAGE_TABLE_INSTRUCTION, // Page table data (e.g., PTEs for instruction pages)
		UTOPIA_FP,           // Utopia Frame Pointer Array metadata
		UTOPIA_TAR,          // Utopia Tag Array metadata
		UTOPIA_RADIX_INTERNAL, // Utopia RadixWay internal node (pointer array)
		UTOPIA_RADIX_LEAF,     // Utopia RadixWay leaf node (valid+way bitmap)
		INSTRUCTION,         // Instruction fetches
		DATA,                // Regular data accesses
		NUM_BLOCK_TYPES
	};

	// Helper function to check if a block type is metadata (any translation-related block)
	static inline bool isMetadataBlockType(block_type_t block_type) {
		return (block_type == PAGE_TABLE_DATA || 
		        block_type == PAGE_TABLE_INSTRUCTION ||
		        block_type == UTOPIA_FP || 
		        block_type == UTOPIA_TAR ||
		        block_type == UTOPIA_RADIX_INTERNAL ||
		        block_type == UTOPIA_RADIX_LEAF);
	}
	
	// For backward compatibility - PAGE_TABLE is an alias for PAGE_TABLE_DATA
	static const block_type_t PAGE_TABLE = PAGE_TABLE_DATA;

	static const UInt8 BitsUsedOffset = 3; // Track usage on 1<<BitsUsedOffset granularity (per 64-bit / 8-byte)
	typedef UInt8 BitsUsedType;			   // Enough to store one bit per 1<<BitsUsedOffset byte element per cache line (8 8-byte elements for 64-byte cache lines)
										   // This can be extended later to include other information
										   // for different cache coherence protocols
private:

	// @kanellok for TLB: added ppn to store the physical page number
	IntPtr ppn;
	bool m_tlb_entry;	  // @kanellok for caches that store TLB entries: flag to indicate if this is a TLB entry
	int m_page_size;	  //@kanellok for TLBs: hold page size for each cache block

	IntPtr m_tag;
	CacheState::cstate_t m_cstate;
	UInt64 m_owner;
	BitsUsedType m_used;
	UInt8 m_options; // large enough to hold a bitfield for all available option_t's
	block_type_t m_block_type;
	int m_reuse; //@kanellok tracking reuse
	int utilization;

	static const char *option_names[];

public:
	PTEFootprintStats pte_stats;
	CacheBlockInfo(IntPtr tag = ~0,
				   CacheState::cstate_t cstate = CacheState::INVALID,
				   UInt64 options = 0);

	virtual ~CacheBlockInfo();

	static CacheBlockInfo *create(CacheBase::cache_t cache_type);
	virtual void invalidate(void);
	virtual void clone(CacheBlockInfo *cache_block_info);

	bool isValid() const { return (m_tag != ((IntPtr)~0)); }


	IntPtr getTag() const { return m_tag; }

	CacheState::cstate_t getCState() const { return m_cstate; }

	void setTag(IntPtr tag) { m_tag = tag; }

	void setCState(CacheState::cstate_t cstate) { m_cstate = cstate; }
	void setPPN(IntPtr _ppn) { ppn = _ppn; };
	IntPtr getPPN() { return ppn; };
	UInt64 getOwner() const { return m_owner; }
	void setOwner(UInt64 owner) { m_owner = owner; }

	bool hasOption(option_t option) { return m_options & (1 << option); }
	void setOption(option_t option) { m_options |= (1 << option); }
	void clearOption(option_t option) { m_options &= ~(UInt64(1) << option); }

	inline void setBlockType(block_type_t bt) { m_block_type = bt; }
	inline block_type_t getBlockType() { return m_block_type; }
	inline bool isPageTableBlock() { return isMetadataBlockType(m_block_type); }
	inline bool isInstructionBlock() { return (m_block_type == block_type_t::INSTRUCTION); }
	inline bool isDataBlock() { return (m_block_type == block_type_t::DATA); }

	void setPageSize(int pagesize) { m_page_size = pagesize; }


	int getPageSize() { return m_page_size; }

	BitsUsedType getUsage() const { return m_used; };
	bool updateUsage(UInt32 offset, UInt32 size);
	bool updateUsage(BitsUsedType used);

	static const char *getOptionName(option_t option);

	void increaseReuse() { m_reuse++; }
	int getReuse() { return m_reuse; }
};

class CacheCntlr
{
public:
	virtual bool isInLowerLevelCache(CacheBlockInfo *block_info) { return false; }
	virtual void incrementQBSLookupCost() {}
};

#endif /* __CACHE_BLOCK_INFO_H__ */
