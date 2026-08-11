#ifndef SAFARTLB_H
#define SAFARTLB_H

#include "cache.h"
#include <unordered_map>
#include <vector>

class SafarTlbCache : public Cache
{
private:
    struct TagEntry {
        bool valid;
        IntPtr tag;
        UInt32 data_index;
        UInt64 last_access;
    };

    struct DataEntry {
        bool valid;
        IntPtr tag;
        CacheBlockInfo::block_type_t btype;
        int page_size;
        IntPtr ppn;
        UInt8 options;
    };

    UInt32 m_num_sets;
    UInt32 m_associativity;
    UInt32 m_capacity;

    std::vector<std::vector<TagEntry>> m_tag_array; // Tag array: m_num_sets x m_associativity
    std::vector<DataEntry> m_data_array;           // Data array: Fully-associative, size m_capacity
    std::vector<CacheBlockInfo*> m_data_blocks;    // CacheBlockInfo wrappers for each data entry

    UInt32 m_head;
    UInt32 m_tail;
    UInt64 m_access_counter;

    // Helper to find data index by tag and set index
    int findDataIndex(IntPtr tag, UInt32 set_index) const;

public:
    SafarTlbCache(String name,
                  String cfgname,
                  core_id_t core_id,
                  UInt32 num_sets,
                  UInt32 associativity, UInt32 cache_block_size,
                  String replacement_policy,
                  cache_t cache_type,
                  hash_t hash = CacheBase::HASH_MASK,
                  FaultInjector *fault_injector = NULL,
                  AddressHomeLookup *ahl = NULL, bool is_tlb = false, int *page_size = NULL, int number_of_page_sizes = 0);
    
    virtual ~SafarTlbCache();

    virtual bool invalidateSingleLine(IntPtr addr) override;
    virtual bool invalidateSingleLineTLB(IntPtr addr, int page_size) override;
    virtual bool containsTLB(IntPtr addr, int page_size) const override;
    
    virtual CacheBlockInfo *accessSingleLine(IntPtr addr,
                                             access_t access_type, Byte *buff, UInt32 bytes, SubsecondTime now, bool update_replacement, bool tlb_entry = false, bool is_metadata = false) override;
    
    virtual CacheBlockInfo *accessSingleLineTLB(IntPtr addr,
                                                access_t access_type, Byte *buff, UInt32 bytes, SubsecondTime now, bool update_replacement) override;

    virtual void insertSingleLine(IntPtr addr, Byte *fill_buff,
                                  bool *eviction, IntPtr *evict_addr,
                                  CacheBlockInfo *evict_block_info, Byte *evict_buff, SubsecondTime now, CacheCntlr *cntlr = NULL, CacheBlockInfo::block_type_t btype = CacheBlockInfo::block_type_t::DATA) override;
    
    virtual void insertSingleLineTLB(IntPtr addr, Byte *fill_buff,
                                     bool *eviction, IntPtr *evict_addr,
                                     CacheBlockInfo *evict_block_info, Byte *evict_buff, SubsecondTime now, CacheCntlr *cntlr = NULL, CacheBlockInfo::block_type_t btype = CacheBlockInfo::block_type_t::DATA, int page_size = 12, IntPtr ppn = 0) override;

    virtual CacheBlockInfo *peekSingleLine(IntPtr addr) override;
};

#endif // SAFARTLB_H
