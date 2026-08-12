#include "safartlb.h"
#include "simulator.h"
#include <algorithm>
#include <iostream>

SafarTlbCache::SafarTlbCache(String name,
                             String cfgname,
                             core_id_t core_id,
                             UInt32 num_sets,
                             UInt32 associativity, UInt32 cache_block_size,
                             String replacement_policy,
                             cache_t cache_type,
                             hash_t hash,
                             FaultInjector *fault_injector,
                             AddressHomeLookup *ahl, bool is_tlb, int *page_size, int number_of_page_sizes)
    : Cache(name, cfgname, core_id, num_sets, associativity, cache_block_size, "lru", cache_type, hash, fault_injector, ahl, is_tlb, page_size, number_of_page_sizes)
    , m_num_sets(num_sets)
    , m_associativity(associativity)
    , m_capacity(num_sets * associativity)
    , m_head(0)
    , m_tail(0)
    , m_access_counter(0)
{
    m_tag_array.resize(m_num_sets, std::vector<TagEntry>(m_associativity, {false, 0, 0, 0}));
    m_data_array.resize(m_capacity, {false, 0, CacheBlockInfo::block_type_t::DATA, 12, 0, 0});
    
    m_data_blocks.resize(m_capacity);
    for (UInt32 i = 0; i < m_capacity; ++i) {
        m_data_blocks[i] = CacheBlockInfo::create(m_cache_type);
        m_data_blocks[i]->invalidate();
    }
}

SafarTlbCache::~SafarTlbCache()
{
    for (UInt32 i = 0; i < m_capacity; ++i) {
        delete m_data_blocks[i];
    }
}

int SafarTlbCache::findDataIndex(IntPtr tag, UInt32 set_index) const
{
    if (set_index >= m_num_sets) return -1;
    for (UInt32 way = 0; way < m_associativity; ++way) {
        if (m_tag_array[set_index][way].valid && m_tag_array[set_index][way].tag == tag) {
            return m_tag_array[set_index][way].data_index;
        }
    }
    return -1;
}

bool SafarTlbCache::invalidateSingleLine(IntPtr addr)
{
    IntPtr tag;
    UInt32 set_index;
    splitAddress(addr, tag, set_index);

    int idx = findDataIndex(tag, set_index);
    if (idx != -1) {
        m_data_array[idx].valid = false;
        m_data_blocks[idx]->invalidate();

        // Invalidate tag entry
        for (UInt32 way = 0; way < m_associativity; ++way) {
            if (m_tag_array[set_index][way].valid && m_tag_array[set_index][way].tag == tag) {
                m_tag_array[set_index][way].valid = false;
                break;
            }
        }

        // Fill the hole with tail block
        if (idx != (int)m_tail) {
            if (m_data_array[m_tail].valid) {
                // Copy tail to hole
                m_data_array[idx] = m_data_array[m_tail];
                m_data_blocks[idx]->clone(m_data_blocks[m_tail]);
                m_data_blocks[idx]->setTag(m_data_array[idx].tag);

                // Update tag array mapping
                bool updated = false;
                for (UInt32 s = 0; s < m_num_sets; ++s) {
                    for (UInt32 w = 0; w < m_associativity; ++w) {
                        if (m_tag_array[s][w].valid && m_tag_array[s][w].data_index == m_tail) {
                            m_tag_array[s][w].data_index = idx;
                            updated = true;
                            break;
                        }
                    }
                    if (updated) break;
                }
            }
            m_data_array[m_tail].valid = false;
            m_data_blocks[m_tail]->invalidate();
            m_tail = (m_tail + 1) % m_capacity;
        } else {
            m_tail = (m_tail + 1) % m_capacity;
        }
        return true;
    }
    return false;
}

bool SafarTlbCache::invalidateSingleLineTLB(IntPtr addr, int page_size)
{
    // For TLB, search across possible page sizes
    bool result = false;
    for (int ps = 0; ps < m_number_of_page_sizes; ps++) {
        IntPtr tag;
        UInt32 set_index;
        int current_page_size = m_pagesizes[ps];
        splitAddressTLB(addr, tag, set_index, current_page_size);

        int idx = findDataIndex(tag, set_index);
        if (idx != -1 && m_data_array[idx].page_size == page_size) {
            m_data_array[idx].valid = false;
            m_data_blocks[idx]->invalidate();

            for (UInt32 way = 0; way < m_associativity; ++way) {
                if (m_tag_array[set_index][way].valid && m_tag_array[set_index][way].tag == tag) {
                    m_tag_array[set_index][way].valid = false;
                    break;
                }
            }

            // Fill the hole with tail block
            if (idx != (int)m_tail) {
                if (m_data_array[m_tail].valid) {
                    m_data_array[idx] = m_data_array[m_tail];
                    m_data_blocks[idx]->clone(m_data_blocks[m_tail]);
                    m_data_blocks[idx]->setTag(m_data_array[idx].tag);

                    bool updated = false;
                    for (UInt32 s = 0; s < m_num_sets; ++s) {
                        for (UInt32 w = 0; w < m_associativity; ++w) {
                            if (m_tag_array[s][w].valid && m_tag_array[s][w].data_index == m_tail) {
                                m_tag_array[s][w].data_index = idx;
                                updated = true;
                                break;
                            }
                        }
                        if (updated) break;
                    }
                }
                m_data_array[m_tail].valid = false;
                m_data_blocks[m_tail]->invalidate();
                m_tail = (m_tail + 1) % m_capacity;
            } else {
                m_tail = (m_tail + 1) % m_capacity;
            }
            result = true;
        }
    }
    return result;
}

bool SafarTlbCache::containsTLB(IntPtr addr, int page_size) const
{
    for (int ps = 0; ps < m_number_of_page_sizes; ps++) {
        IntPtr tag;
        UInt32 set_index;
        int current_page_size = m_pagesizes[ps];
        splitAddressTLB(addr, tag, set_index, current_page_size);

        int idx = findDataIndex(tag, set_index);
        if (idx != -1 && m_data_array[idx].page_size == page_size) {
            return true;
        }
    }
    return false;
}

CacheBlockInfo* SafarTlbCache::accessSingleLine(IntPtr addr,
                                                access_t access_type, Byte *buff, UInt32 bytes, SubsecondTime now, bool update_replacement, bool tlb_entry, bool is_metadata)
{
    IntPtr tag;
    UInt32 set_index;
    splitAddress(addr, tag, set_index);

    int idx = findDataIndex(tag, set_index);
    if (idx == -1) return NULL;

    m_access_counter++;
    for (UInt32 way = 0; way < m_associativity; ++way) {
        if (m_tag_array[set_index][way].valid && m_tag_array[set_index][way].tag == tag) {
            if (update_replacement) {
                m_tag_array[set_index][way].last_access = m_access_counter;
            }
            break;
        }
    }

    CacheBlockInfo *block = m_data_blocks[idx];
    block->setTag(tag);
    block->setBlockType(m_data_array[idx].btype);
    block->setPageSize(m_data_array[idx].page_size);
    block->setPPN(m_data_array[idx].ppn);
    block->setCState(CacheState::SHARED);
    return block;
}

CacheBlockInfo* SafarTlbCache::accessSingleLineTLB(IntPtr addr,
                                                   access_t access_type, Byte *buff, UInt32 bytes, SubsecondTime now, bool update_replacement)
{
    for (int ps = 0; ps < m_number_of_page_sizes; ps++) {
        IntPtr tag;
        UInt32 set_index;
        int current_page_size = m_pagesizes[ps];
        splitAddressTLB(addr, tag, set_index, current_page_size);

        int idx = findDataIndex(tag, set_index);
        if (idx != -1) {
            m_access_counter++;
            for (UInt32 way = 0; way < m_associativity; ++way) {
                if (m_tag_array[set_index][way].valid && m_tag_array[set_index][way].tag == tag) {
                    if (update_replacement) {
                        m_tag_array[set_index][way].last_access = m_access_counter;
                    }
                    break;
                }
            }

            CacheBlockInfo *block = m_data_blocks[idx];
            block->setTag(tag);
            block->setBlockType(m_data_array[idx].btype);
            block->setPageSize(m_data_array[idx].page_size);
            block->setPPN(m_data_array[idx].ppn);
            block->setCState(CacheState::SHARED);
            return block;
        }
    }
    return NULL;
}

void SafarTlbCache::insertSingleLine(IntPtr addr, Byte *fill_buff,
                                     bool *eviction, IntPtr *evict_addr,
                                     CacheBlockInfo *evict_block_info, Byte *evict_buff, SubsecondTime now, CacheCntlr *cntlr, CacheBlockInfo::block_type_t btype)
{
    IntPtr tag;
    UInt32 set_index;
    splitAddress(addr, tag, set_index);

    *eviction = false;

    if (m_is_stlb) {
        recordSTLBInsert(set_index, addr);
    }

    // Check if tag already exists in the set
    int existing_idx = findDataIndex(tag, set_index);
    if (existing_idx != -1) {
        m_data_array[existing_idx].btype = btype;
        m_data_blocks[existing_idx]->setBlockType(btype);
        return;
    }

    // Find free way in tag array
    int tag_way = -1;
    for (UInt32 way = 0; way < m_associativity; ++way) {
        if (!m_tag_array[set_index][way].valid) {
            tag_way = way;
            break;
        }
    }

    // If tag array is full, evict a tag (SAC replacement)
    if (tag_way == -1) {
        tag_way = 0;
        UInt64 min_access = m_tag_array[set_index][0].last_access;
        for (UInt32 way = 1; way < m_associativity; ++way) {
            if (m_tag_array[set_index][way].last_access < min_access) {
                min_access = m_tag_array[set_index][way].last_access;
                tag_way = way;
            }
        }

        // Invalidate victim tag and trigger eviction
        UInt32 victim_data_idx = m_tag_array[set_index][tag_way].data_index;
        *eviction = true;
        *evict_addr = tagToAddress(m_data_blocks[victim_data_idx]->getTag());
        evict_block_info->clone(m_data_blocks[victim_data_idx]);
        evict_block_info->setTag(m_data_array[victim_data_idx].tag);
        
        recordEviction(m_data_blocks[victim_data_idx]);
        if (m_is_stlb) {
            recordSTLBEvict(set_index, *evict_addr);
        }

        m_data_array[victim_data_idx].valid = false;
        m_data_blocks[victim_data_idx]->invalidate();
        m_tag_array[set_index][tag_way].valid = false;

        // Shift Tail to fill the hole
        if (victim_data_idx != m_tail) {
            if (m_data_array[m_tail].valid) {
                m_data_array[victim_data_idx] = m_data_array[m_tail];
                m_data_blocks[victim_data_idx]->clone(m_data_blocks[m_tail]);
                m_data_blocks[victim_data_idx]->setTag(m_data_array[victim_data_idx].tag);

                bool updated = false;
                for (UInt32 s = 0; s < m_num_sets; ++s) {
                    for (UInt32 w = 0; w < m_associativity; ++w) {
                        if (m_tag_array[s][w].valid && m_tag_array[s][w].data_index == m_tail) {
                            m_tag_array[s][w].data_index = victim_data_idx;
                            updated = true;
                            break;
                        }
                    }
                    if (updated) break;
                }
            }
            m_data_array[m_tail].valid = false;
            m_data_blocks[m_tail]->invalidate();
            m_tail = (m_tail + 1) % m_capacity;
        } else {
            m_tail = (m_tail + 1) % m_capacity;
        }
    }

    // Insert at Head (virtual FIFO boundary)
    if (m_data_array[m_head].valid) {
        // Queue is full, evict Head (which is Tail)
        *eviction = true;
        *evict_addr = tagToAddress(m_data_blocks[m_head]->getTag());
        evict_block_info->clone(m_data_blocks[m_head]);
        evict_block_info->setTag(m_data_array[m_head].tag);

        recordEviction(m_data_blocks[m_head]);
        if (m_is_stlb) {
            recordSTLBEvict(set_index, *evict_addr);
        }

        // Invalidate corresponding tag
        bool tag_invalidated = false;
        for (UInt32 s = 0; s < m_num_sets; ++s) {
            for (UInt32 w = 0; w < m_associativity; ++w) {
                if (m_tag_array[s][w].valid && m_tag_array[s][w].data_index == m_head) {
                    m_tag_array[s][w].valid = false;
                    tag_invalidated = true;
                    break;
                }
            }
            if (tag_invalidated) break;
        }

        m_data_array[m_head].valid = false;
        m_data_blocks[m_head]->invalidate();
        m_tail = (m_tail + 1) % m_capacity;
    }

    // Allocate new block at Head
    m_data_array[m_head].valid = true;
    m_data_array[m_head].tag = tag;
    m_data_array[m_head].btype = btype;
    m_data_array[m_head].page_size = 12;
    m_data_array[m_head].ppn = 0;
    
    m_data_blocks[m_head]->setTag(tag);
    m_data_blocks[m_head]->setBlockType(btype);
    m_data_blocks[m_head]->setCState(CacheState::SHARED);

    // Update tag array entry
    m_tag_array[set_index][tag_way].valid = true;
    m_tag_array[set_index][tag_way].tag = tag;
    m_tag_array[set_index][tag_way].data_index = m_head;
    m_access_counter++;
    m_tag_array[set_index][tag_way].last_access = m_access_counter;

    m_head = (m_head + 1) % m_capacity;
}

void SafarTlbCache::insertSingleLineTLB(IntPtr addr, Byte *fill_buff,
                                        bool *eviction, IntPtr *evict_addr,
                                        CacheBlockInfo *evict_block_info, Byte *evict_buff, SubsecondTime now, CacheCntlr *cntlr, CacheBlockInfo::block_type_t btype, int page_size, IntPtr ppn)
{
    IntPtr tag;
    UInt32 set_index;
    splitAddressTLB(addr, tag, set_index, page_size);

    *eviction = false;

    if (m_is_stlb) {
        recordSTLBInsert(set_index, addr);
    }

    // Check if tag already exists in the set
    int existing_idx = findDataIndex(tag, set_index);
    if (existing_idx != -1) {
        m_data_array[existing_idx].btype = btype;
        m_data_array[existing_idx].page_size = page_size;
        m_data_array[existing_idx].ppn = ppn;
        m_data_blocks[existing_idx]->setBlockType(btype);
        m_data_blocks[existing_idx]->setPageSize(page_size);
        m_data_blocks[existing_idx]->setPPN(ppn);
        return;
    }

    // Find free way in tag array
    int tag_way = -1;
    for (UInt32 way = 0; way < m_associativity; ++way) {
        if (!m_tag_array[set_index][way].valid) {
            tag_way = way;
            break;
        }
    }

    // If tag array is full, evict a tag
    if (tag_way == -1) {
        tag_way = 0;
        UInt64 min_access = m_tag_array[set_index][0].last_access;
        for (UInt32 way = 1; way < m_associativity; ++way) {
            if (m_tag_array[set_index][way].last_access < min_access) {
                min_access = m_tag_array[set_index][way].last_access;
                tag_way = way;
            }
        }

        UInt32 victim_data_idx = m_tag_array[set_index][tag_way].data_index;
        *eviction = true;
        *evict_addr = tagToAddressTLB(m_data_blocks[victim_data_idx]->getTag(), m_data_array[victim_data_idx].page_size);
        evict_block_info->clone(m_data_blocks[victim_data_idx]);
        evict_block_info->setTag(m_data_array[victim_data_idx].tag);
        evict_block_info->setPageSize(m_data_array[victim_data_idx].page_size);

        recordEviction(m_data_blocks[victim_data_idx]);
        if (m_is_stlb) {
            recordSTLBEvict(set_index, *evict_addr);
        }

        m_data_array[victim_data_idx].valid = false;
        m_data_blocks[victim_data_idx]->invalidate();
        m_tag_array[set_index][tag_way].valid = false;

        // Shift Tail to fill the hole
        if (victim_data_idx != m_tail) {
            if (m_data_array[m_tail].valid) {
                m_data_array[victim_data_idx] = m_data_array[m_tail];
                m_data_blocks[victim_data_idx]->clone(m_data_blocks[m_tail]);
                m_data_blocks[victim_data_idx]->setTag(m_data_array[victim_data_idx].tag);

                bool updated = false;
                for (UInt32 s = 0; s < m_num_sets; ++s) {
                    for (UInt32 w = 0; w < m_associativity; ++w) {
                        if (m_tag_array[s][w].valid && m_tag_array[s][w].data_index == m_tail) {
                            m_tag_array[s][w].data_index = victim_data_idx;
                            updated = true;
                            break;
                        }
                    }
                    if (updated) break;
                }
            }
            m_data_array[m_tail].valid = false;
            m_data_blocks[m_tail]->invalidate();
            m_tail = (m_tail + 1) % m_capacity;
        } else {
            m_tail = (m_tail + 1) % m_capacity;
        }
    }

    // Insert at Head
    if (m_data_array[m_head].valid) {
        *eviction = true;
        *evict_addr = tagToAddressTLB(m_data_blocks[m_head]->getTag(), m_data_array[m_head].page_size);
        evict_block_info->clone(m_data_blocks[m_head]);
        evict_block_info->setTag(m_data_array[m_head].tag);
        evict_block_info->setPageSize(m_data_array[m_head].page_size);

        recordEviction(m_data_blocks[m_head]);
        if (m_is_stlb) {
            recordSTLBEvict(set_index, *evict_addr);
        }

        bool tag_invalidated = false;
        for (UInt32 s = 0; s < m_num_sets; ++s) {
            for (UInt32 w = 0; w < m_associativity; ++w) {
                if (m_tag_array[s][w].valid && m_tag_array[s][w].data_index == m_head) {
                    m_tag_array[s][w].valid = false;
                    tag_invalidated = true;
                    break;
                }
            }
            if (tag_invalidated) break;
        }

        m_data_array[m_head].valid = false;
        m_data_blocks[m_head]->invalidate();
        m_tail = (m_tail + 1) % m_capacity;
    }

    m_data_array[m_head].valid = true;
    m_data_array[m_head].tag = tag;
    m_data_array[m_head].btype = btype;
    m_data_array[m_head].page_size = page_size;
    m_data_array[m_head].ppn = ppn;

    m_data_blocks[m_head]->setTag(tag);
    m_data_blocks[m_head]->setBlockType(btype);
    m_data_blocks[m_head]->setPageSize(page_size);
    m_data_blocks[m_head]->setPPN(ppn);
    m_data_blocks[m_head]->setCState(CacheState::SHARED);

    m_tag_array[set_index][tag_way].valid = true;
    m_tag_array[set_index][tag_way].tag = tag;
    m_tag_array[set_index][tag_way].data_index = m_head;
    m_access_counter++;
    m_tag_array[set_index][tag_way].last_access = m_access_counter;

    m_head = (m_head + 1) % m_capacity;
}

CacheBlockInfo* SafarTlbCache::peekSingleLine(IntPtr addr)
{
    IntPtr tag;
    UInt32 set_index;
    splitAddress(addr, tag, set_index);

    int idx = findDataIndex(tag, set_index);
    if (idx != -1) {
        CacheBlockInfo *block = m_data_blocks[idx];
        block->setTag(tag);
        block->setBlockType(m_data_array[idx].btype);
        block->setPageSize(m_data_array[idx].page_size);
        block->setPPN(m_data_array[idx].ppn);
        block->setCState(CacheState::SHARED);
        return block;
    }
    return NULL;
}
